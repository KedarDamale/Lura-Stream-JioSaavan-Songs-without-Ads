from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, FileResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import jiosaavn_client as jiosaavn
import os
import io
import tempfile
import re
import requests
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, USLT, TDRC, SYLT
from mutagen import File as MutagenFile
from mutagen.id3 import ID3NoHeaderError
from pydub import AudioSegment
from pydub.utils import which
import shutil


app = FastAPI(title="KedarMusic JioSaavn API", version="1.0.0")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home() -> RedirectResponse:
    # Redirect to UI template
    return RedirectResponse(url="/ui")


@app.get("/ui", response_class=HTMLResponse)
def ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/song/")
def search(
    query: Optional[str] = Query(None, description="Search text or JioSaavn song URL"),
    lyrics: bool = Query(False, description="Include lyrics in response"),
    songdata: bool = Query(True, description="If true, fetch full song objects; else, return raw search results"),
) -> JSONResponse:
    if not query:
        return JSONResponse(
            {"status": False, "error": "Query is required to search songs!"}, status_code=400
        )
    data = jiosaavn.search_for_song(query, lyrics, songdata)
    return JSONResponse(content=data)


@app.get("/song/get/")
def get_song(id: Optional[str] = Query(None), lyrics: bool = Query(False)) -> JSONResponse:
    if not id:
        return JSONResponse(
            {"status": False, "error": "Song ID is required to get a song!"}, status_code=400
        )
    resp = jiosaavn.get_song(id, lyrics)
    if not resp:
        return JSONResponse({"status": False, "error": "Invalid Song ID received!"}, status_code=404)
    return JSONResponse(content=resp)


@app.get("/playlist/")
def playlist(query: Optional[str] = Query(None), lyrics: bool = Query(False)) -> JSONResponse:
    if not query:
        return JSONResponse(
            {"status": False, "error": "Query is required to search playlists!"}, status_code=400
        )
    list_id = jiosaavn.get_playlist_id(query)
    songs = jiosaavn.get_playlist(list_id, lyrics)
    return JSONResponse(content=songs)


@app.get("/album/")
def album(query: Optional[str] = Query(None), lyrics: bool = Query(False)) -> JSONResponse:
    if not query:
        return JSONResponse(
            {"status": False, "error": "Query is required to search albums!"}, status_code=400
        )
    album_id = jiosaavn.get_album_id(query)
    songs = jiosaavn.get_album(album_id, lyrics)
    return JSONResponse(content=songs)


@app.get("/lyrics/")
def lyrics_endpoint(query: Optional[str] = Query(None)) -> JSONResponse:
    if not query:
        return JSONResponse(
            {
                "status": False,
                "error": "Query containing song link or id is required to fetch lyrics!",
            },
            status_code=400,
        )
    try:
        if ("http" in query) and ("saavn" in query or "jiosaavn" in query):
            song_id = jiosaavn.get_song_id(query)
            lyrics_text = jiosaavn.get_lyrics(song_id)
        else:
            lyrics_text = jiosaavn.get_lyrics(query)
        return JSONResponse({"status": True, "lyrics": lyrics_text})
    except Exception as e:
        return JSONResponse({"status": False, "error": str(e)}, status_code=500)


@app.get("/result/")
def result(query: Optional[str] = Query(None), lyrics: bool = Query(False)) -> JSONResponse:
    if not query:
        return JSONResponse(
            {"status": False, "error": "Query is required!"}, status_code=400
        )

    if "saavn" not in query and "jiosaavn" not in query:
        data = jiosaavn.search_for_song(query, lyrics, True)
        return JSONResponse(content=data)

    try:
        if "/song/" in query:
            song_id = jiosaavn.get_song_id(query)
            song = jiosaavn.get_song(song_id, lyrics)
            return JSONResponse(content=song)
        elif "/album/" in query:
            album_id = jiosaavn.get_album_id(query)
            songs = jiosaavn.get_album(album_id, lyrics)
            return JSONResponse(content=songs)
        elif "/playlist/" in query or "/featured/" in query:
            list_id = jiosaavn.get_playlist_id(query)
            songs = jiosaavn.get_playlist(list_id, lyrics)
            return JSONResponse(content=songs)
    except Exception as e:
        return JSONResponse({"status": False, "error": str(e)}, status_code=500)

    return JSONResponse({"status": False, "error": "Invalid query"}, status_code=400)


def _sanitize_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "song"


@app.get("/download")
def download(
    background_tasks: BackgroundTasks,
    query: Optional[str] = Query(None, description="JioSaavn song link or id"),
    format: str = Query("auto", regex="^(auto|mp3|m4a)$", description="Output format"),
) -> FileResponse:
    if not query:
        raise HTTPException(status_code=400, detail="Query (song link or id) is required")

    # Resolve song id
    if ("http" in query) and ("saavn" in query or "jiosaavn" in query):
        song_id = jiosaavn.get_song_id(query)
    else:
        song_id = query

    song = jiosaavn.get_song(song_id, include_lyrics=True)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    # Download source audio
    media_url = song.get("media_url")
    if not media_url:
        raise HTTPException(status_code=500, detail="Media URL missing")

    src_ext = ".mp4" if ".mp4" in media_url else (".m4a" if media_url.endswith(".m4a") else ".bin")
    src_fd, src_path = tempfile.mkstemp(suffix=src_ext)
    os.close(src_fd)
    with requests.get(media_url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(src_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)

    title = song.get("song") or song.get("title") or "Song"
    artists_text = song.get("primary_artists") or song.get("singers") or ""
    artists = [a.strip() for a in artists_text.split(",") if a.strip()] or [artists_text]
    album = song.get("album") or ""
    year = song.get("year") or ""
    lyrics_text = song.get("lyrics") or ""

    cover_bytes = None
    image_url = song.get("image")
    if image_url:
        try:
            img_resp = requests.get(image_url, timeout=30)
            if img_resp.ok:
                cover_bytes = img_resp.content
        except Exception:
            cover_bytes = None

    filename_base = _sanitize_filename(f"{title} - {artists_text}" if artists_text else title)

    # Choose output format
    chosen_format = format
    if format == "auto":
        chosen_format = "mp3" if (which("ffmpeg") and which("ffprobe")) else "m4a"
    # Graceful fallback: if MP3 requested but ffmpeg not available, switch to m4a silently
    if chosen_format == "mp3" and not (which("ffmpeg") and which("ffprobe")):
        chosen_format = "m4a"

    # Prepare output
    out_suffix = ".mp3" if chosen_format == "mp3" else ".m4a"
    out_fd, out_path = tempfile.mkstemp(suffix=out_suffix)
    os.close(out_fd)

    try:
        if chosen_format == "mp3":
            # Transcode to MP3 using ffmpeg (required by pydub)
            audio = AudioSegment.from_file(src_path)
            audio.export(out_path, format="mp3", bitrate="320k")

            # Embed ID3v2.3 tags for Windows Media Player compatibility
            try:
                id3 = ID3(out_path)
            except ID3NoHeaderError:
                id3 = ID3()

            # Use UTF-16 (encoding=1) for broader Windows Media Player compatibility
            id3.add(TIT2(encoding=1, text=title))
            if artists:
                id3.add(TPE1(encoding=1, text=artists))
            if album:
                id3.add(TALB(encoding=1, text=album))
            if year:
                id3.add(TDRC(encoding=1, text=str(year)))
            if cover_bytes:
                mime = "image/jpeg" if image_url and image_url.lower().endswith(".jpg") or image_url.lower().endswith(".jpeg") else "image/png"
                id3.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_bytes))
            if lyrics_text:
                # Unsynchronized lyrics (USLT) with UTF-16
                id3.add(USLT(encoding=1, lang="eng", desc="", text=lyrics_text))
                # Basic SYLT placeholder: order must be (timestamp_ms, text)
                try:
                    lines = [ln for ln in lyrics_text.splitlines() if ln.strip()]
                    step = 2000  # 2s per line placeholder
                    events = [((i * step), ln) for i, ln in enumerate(lines)]
                    id3.add(SYLT(encoding=1, lang="eng", format=2, type=1, desc="Lyrics", text=events))
                except Exception:
                    pass

            id3.save(out_path, v2_version=3)

        else:  # m4a
            # Avoid ffmpeg: copy original file to output and tag directly
            shutil.copyfile(src_path, out_path)
            from mutagen.mp4 import MP4, MP4Cover
            from mutagen.mp4 import MP4FreeForm

            mp4 = MP4(out_path)
            mp4["\xa9nam"] = title
            if artists_text:
                mp4["\xa9ART"] = artists_text
            if album:
                mp4["\xa9alb"] = album
            if year:
                mp4["\xa9day"] = str(year)
            if lyrics_text:
                # Standard lyrics atom
                mp4["\xa9lyr"] = lyrics_text
                # Freeform iTunes lyrics (improves compatibility across players)
                try:
                    mp4["----:com.apple.iTunes:Lyrics"] = [MP4FreeForm(lyrics_text.encode("utf-8"), MP4FreeForm.UTF8)]
                except Exception:
                    pass
            if cover_bytes:
                image_format = MP4Cover.FORMAT_JPEG if (image_url and (image_url.lower().endswith(".jpg") or image_url.lower().endswith(".jpeg"))) else MP4Cover.FORMAT_PNG
                mp4["covr"] = [MP4Cover(cover_bytes, imageformat=image_format)]
            mp4.save()

    except Exception as e:
        # Cleanup on failure
        try:
            os.remove(out_path)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")
    finally:
        try:
            os.remove(src_path)
        except Exception:
            pass

    background_tasks.add_task(lambda p: os.remove(p), out_path)
    media_type = "audio/mpeg" if chosen_format == "mp3" else "audio/mp4"
    return FileResponse(
        path=out_path,
        media_type=media_type,
        filename=f"{filename_base}{out_suffix}",
        background=background_tasks,
    )


def _to_srt_timestamp(ms: int) -> str:
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _lyrics_to_srt(lyrics_text: str) -> str:
    lines = [ln.strip() for ln in lyrics_text.splitlines() if ln.strip()]
    if not lines:
        return ""
    step = 2000  # 2 seconds per line
    blocks = []
    for idx, line in enumerate(lines, start=1):
        start = (idx - 1) * step
        end = start + step
        blocks.append(f"{idx}\n{_to_srt_timestamp(start)} --> { _to_srt_timestamp(end)}\n{line}\n")
    return "\n".join(blocks)


@app.get("/subtitles.srt")
def subtitles(query: Optional[str] = Query(None)) -> PlainTextResponse:
    if not query:
        raise HTTPException(status_code=400, detail="Query (song link or id) is required")

    # Resolve song id
    if ("http" in query) and ("saavn" in query or "jiosaavn" in query):
        song_id = jiosaavn.get_song_id(query)
    else:
        song_id = query

    song = jiosaavn.get_song(song_id, include_lyrics=True)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    lyrics_text = (song.get("lyrics") or "").strip()
    if not lyrics_text:
        raise HTTPException(status_code=404, detail="Lyrics not available for this song")

    srt = _lyrics_to_srt(lyrics_text)
    if not srt:
        raise HTTPException(status_code=404, detail="Unable to generate subtitles from lyrics")

    title = song.get("song") or song.get("title") or "lyrics"
    artists_text = song.get("primary_artists") or song.get("singers") or ""
    base = _sanitize_filename(f"{title} - {artists_text}" if artists_text else title)
    filename = base + ".srt"
    headers = {"Content-Disposition": f"attachment; filename=\"{filename}\""}
    return PlainTextResponse(content=srt, media_type="application/x-subrip", headers=headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="localhost", port=5100, reload=True)


