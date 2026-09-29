"""Lura: a FastAPI-powered JioSaavn discovery and playback service.

The browser and mobile apps stream through the ``/stream`` route. Audio is
relayed in small chunks and is never persisted by the server during playback.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Iterator, Literal
from urllib.parse import urlparse

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from mutagen.id3 import APIC, TALB, TIT2, TDRC, TPE1, USLT, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from pydub import AudioSegment
from pydub.utils import which

import jiosaavn_client as jiosaavn

logger = logging.getLogger("lura")
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CORS_ORIGINS = "http://localhost:5100,http://127.0.0.1:5100"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]

app = FastAPI(
    title="Lura",
    description="Search, stream, and download JioSaavn music.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url=None,
)
app.add_middleware(GZipMiddleware, minimum_size=800)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type", "Range"],
    expose_headers=["Accept-Ranges", "Content-Length", "Content-Range"],
)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _error(message: str, status_code: int) -> JSONResponse:
    """Return the error envelope retained for compatibility with the old API."""
    return JSONResponse({"status": False, "error": message}, status_code=status_code)


def _sanitize_filename(name: str) -> str:
    clean_name = re.sub(r"[\\\\/:*?\"<>|]", " ", name)
    clean_name = re.sub(r"\s+", " ", clean_name).strip(" .")
    return clean_name[:180] or "song"


def _is_jiosaavn_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (
        hostname == "saavn.com"
        or hostname.endswith(".saavn.com")
        or hostname == "jiosaavn.com"
        or hostname.endswith(".jiosaavn.com")
    )


def _song_id_from_query(query: str) -> str:
    """Resolve a JioSaavn URL or accept a provider-specific song ID."""
    if query.startswith(("http://", "https://")):
        if not _is_jiosaavn_url(query):
            raise HTTPException(status_code=400, detail="Only JioSaavn URLs are supported")
        return jiosaavn.get_song_id(query)
    return query


def _to_srt_timestamp(milliseconds: int) -> str:
    hours = milliseconds // 3_600_000
    minutes = (milliseconds % 3_600_000) // 60_000
    seconds = (milliseconds % 60_000) // 1_000
    millis = milliseconds % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _lyrics_to_srt(lyrics_text: str) -> str:
    """Create readable, evenly timed subtitles when synced lyrics are absent."""
    lines = [line.strip() for line in lyrics_text.splitlines() if line.strip()]
    blocks = []
    for index, line in enumerate(lines, start=1):
        start = (index - 1) * 2_000
        blocks.append(
            f"{index}\n{_to_srt_timestamp(start)} --> {_to_srt_timestamp(start + 2_000)}\n{line}\n"
        )
    return "\n".join(blocks)


def _download_file(url: str, destination: str) -> None:
    with requests.get(url, stream=True, timeout=(10, 90)) as response:
        response.raise_for_status()
        with open(destination, "wb") as audio_file:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    audio_file.write(chunk)


def _image_bytes(image_url: str | None) -> bytes | None:
    if not image_url:
        return None
    try:
        response = requests.get(image_url, timeout=(5, 20))
        response.raise_for_status()
        return response.content
    except requests.RequestException:
        logger.info("Artwork download failed", exc_info=True)
        return None


def _image_is_jpeg(image_url: str | None) -> bool:
    return bool(image_url and image_url.lower().split("?", maxsplit=1)[0].endswith((".jpg", ".jpeg")))


def _add_mp3_metadata(
    output_path: str,
    *,
    title: str,
    artists: list[str],
    album: str,
    year: str,
    lyrics: str,
    artwork: bytes | None,
    artwork_url: str | None,
) -> None:
    try:
        tags = ID3(output_path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(TIT2(encoding=3, text=title))
    if artists:
        tags.add(TPE1(encoding=3, text=artists))
    if album:
        tags.add(TALB(encoding=3, text=album))
    if year:
        tags.add(TDRC(encoding=3, text=year))
    if lyrics:
        tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))
    if artwork:
        tags.add(
            APIC(
                encoding=3,
                mime="image/jpeg" if _image_is_jpeg(artwork_url) else "image/png",
                type=3,
                desc="Cover",
                data=artwork,
            )
        )
    tags.save(output_path, v2_version=3)


def _add_m4a_metadata(
    output_path: str,
    *,
    title: str,
    artists: str,
    album: str,
    year: str,
    lyrics: str,
    artwork: bytes | None,
    artwork_url: str | None,
) -> None:
    tags = MP4(output_path)
    tags["\xa9nam"] = title
    if artists:
        tags["\xa9ART"] = artists
    if album:
        tags["\xa9alb"] = album
    if year:
        tags["\xa9day"] = year
    if lyrics:
        tags["\xa9lyr"] = lyrics
        tags["----:com.apple.iTunes:Lyrics"] = [
            MP4FreeForm(lyrics.encode("utf-8"), MP4FreeForm.UTF8)
        ]
    if artwork:
        artwork_format = MP4Cover.FORMAT_JPEG if _image_is_jpeg(artwork_url) else MP4Cover.FORMAT_PNG
        tags["covr"] = [MP4Cover(artwork, imageformat=artwork_format)]
    tags.save()


def _stream_chunks(response: requests.Response) -> Iterator[bytes]:
    """Yield upstream audio without writing it to persistent storage."""
    try:
        yield from response.iter_content(chunk_size=64 * 1024)
    finally:
        response.close()


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"app_name": "KedarMusic"})


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "lura"}


@app.get("/song/", tags=["catalog"])
def search(
    query: str | None = Query(default=None, description="Search text or JioSaavn song URL"),
    lyrics: bool = Query(default=False, description="Include lyrics in the response"),
    songdata: bool = Query(default=True, description="Fetch full song objects"),
) -> JSONResponse:
    if not query or not query.strip():
        return _error("Query is required to search songs", 400)
    try:
        return JSONResponse(content=jiosaavn.search_for_song(query.strip(), lyrics, songdata))
    except requests.RequestException:
        logger.warning("Song search failed", exc_info=True)
        return _error("Music provider is currently unavailable", 502)


@app.get("/song/get/", tags=["catalog"])
def get_song(song_id: str | None = Query(default=None), lyrics: bool = Query(default=False)) -> JSONResponse:
    if not song_id or not song_id.strip():
        return _error("Song ID is required", 400)
    song = jiosaavn.get_song(song_id.strip(), lyrics)
    if not song:
        return _error("Song not found", 404)
    return JSONResponse(content=song)


@app.get("/playlist/", tags=["catalog"])
def playlist(query: str | None = Query(default=None), lyrics: bool = Query(default=False)) -> JSONResponse:
    if not query or not query.strip():
        return _error("Query is required to fetch a playlist", 400)
    if not _is_jiosaavn_url(query):
        return _error("A JioSaavn playlist URL is required", 400)
    try:
        data = jiosaavn.get_playlist(jiosaavn.get_playlist_id(query), lyrics)
    except (IndexError, requests.RequestException):
        logger.warning("Playlist lookup failed", exc_info=True)
        return _error("Playlist could not be fetched", 502)
    return JSONResponse(content=data)


@app.get("/album/", tags=["catalog"])
def album(query: str | None = Query(default=None), lyrics: bool = Query(default=False)) -> JSONResponse:
    if not query or not query.strip():
        return _error("Query is required to fetch an album", 400)
    if not _is_jiosaavn_url(query):
        return _error("A JioSaavn album URL is required", 400)
    try:
        data = jiosaavn.get_album(jiosaavn.get_album_id(query), lyrics)
    except (IndexError, requests.RequestException):
        logger.warning("Album lookup failed", exc_info=True)
        return _error("Album could not be fetched", 502)
    return JSONResponse(content=data)


@app.get("/lyrics/", tags=["catalog"])
def lyrics_endpoint(query: str | None = Query(default=None)) -> JSONResponse:
    if not query or not query.strip():
        return _error("A song ID or JioSaavn song URL is required", 400)
    try:
        lyrics = jiosaavn.get_lyrics(_song_id_from_query(query.strip()))
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Lyrics lookup failed", exc_info=True)
        return _error(str(exc) or "Lyrics could not be fetched", 502)
    return JSONResponse({"status": True, "lyrics": lyrics})


@app.get("/result/", tags=["catalog"])
def result(query: str | None = Query(default=None), lyrics: bool = Query(default=False)) -> JSONResponse:
    """Resolve search text, song URLs, album URLs, and playlist URLs in one route."""
    if not query or not query.strip():
        return _error("Query is required", 400)
    query = query.strip()
    if not query.startswith(("http://", "https://")):
        try:
            return JSONResponse(content=jiosaavn.search_for_song(query, lyrics, True))
        except (requests.RequestException, ValueError):
            logger.warning("Catalog search failed", exc_info=True)
            return _error("The music catalog could not be searched right now", 502)
    if not _is_jiosaavn_url(query):
        return _error("Only JioSaavn URLs are supported", 400)
    try:
        path = urlparse(query).path
        if "/song/" in path:
            song = jiosaavn.get_song(jiosaavn.get_song_id(query), lyrics)
            return JSONResponse(content=song or {"status": False, "error": "Song not found"})
        if "/album/" in path:
            return JSONResponse(content=jiosaavn.get_album(jiosaavn.get_album_id(query), lyrics))
        if "/playlist/" in path or "/featured/" in path:
            return JSONResponse(content=jiosaavn.get_playlist(jiosaavn.get_playlist_id(query), lyrics))
    except (IndexError, requests.RequestException, ValueError):
        logger.warning("Result lookup failed", exc_info=True)
        return _error("The JioSaavn link could not be resolved", 502)
    return _error("This JioSaavn link type is not supported", 400)


@app.get("/stream", tags=["streaming"])
def stream(
    request: Request,
    query: str | None = Query(default=None, description="JioSaavn song link or song ID"),
) -> StreamingResponse:
    """Proxy a track as a memory-only streaming response, including seeking."""
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="A song ID or JioSaavn song URL is required")
    song = jiosaavn.get_song(_song_id_from_query(query.strip()), include_lyrics=False)
    if not song or not song.get("media_url"):
        raise HTTPException(status_code=404, detail="Stream is not available for this song")
    headers = {"User-Agent": "Lura/2.0"}
    if range_header := request.headers.get("range"):
        headers["Range"] = range_header
    try:
        upstream = requests.get(song["media_url"], headers=headers, stream=True, timeout=(10, 90))
        upstream.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="The audio provider is unavailable") from exc
    response_headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    for header in ("Content-Length", "Content-Range"):
        if value := upstream.headers.get(header):
            response_headers[header] = value
    return StreamingResponse(
        _stream_chunks(upstream),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("Content-Type", "audio/mp4"),
        headers=response_headers,
    )


@app.get("/download", tags=["downloads"])
def download(
    background_tasks: BackgroundTasks,
    query: str | None = Query(default=None, description="JioSaavn song link or song ID"),
    output_format: Literal["auto", "mp3", "m4a"] = Query(default="auto", alias="format"),
) -> FileResponse:
    """Prepare a tagged file for an explicit user download."""
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="A song ID or JioSaavn song URL is required")
    song = jiosaavn.get_song(_song_id_from_query(query.strip()), include_lyrics=True)
    if not song or not song.get("media_url"):
        raise HTTPException(status_code=404, detail="Song is not available for download")
    source_fd, source_path = tempfile.mkstemp(suffix=".m4a")
    os.close(source_fd)
    destination_path: str | None = None
    try:
        _download_file(song["media_url"], source_path)
        title = song.get("song") or song.get("title") or "Song"
        artists_text = song.get("primary_artists") or song.get("singers") or ""
        artists = [artist.strip() for artist in artists_text.split(",") if artist.strip()]
        album_name = song.get("album") or ""
        release_year = str(song.get("year") or "")
        lyrics = song.get("lyrics") or ""
        artwork_url = song.get("image")
        artwork = _image_bytes(artwork_url)
        chosen_format = output_format
        if chosen_format == "auto":
            chosen_format = "mp3" if which("ffmpeg") and which("ffprobe") else "m4a"
        if chosen_format == "mp3" and not (which("ffmpeg") and which("ffprobe")):
            raise HTTPException(status_code=503, detail="MP3 conversion requires ffmpeg and ffprobe")
        destination_fd, destination_path = tempfile.mkstemp(suffix=f".{chosen_format}")
        os.close(destination_fd)
        if chosen_format == "mp3":
            AudioSegment.from_file(source_path).export(destination_path, format="mp3", bitrate="320k")
            _add_mp3_metadata(
                destination_path,
                title=title,
                artists=artists,
                album=album_name,
                year=release_year,
                lyrics=lyrics,
                artwork=artwork,
                artwork_url=artwork_url,
            )
            media_type = "audio/mpeg"
        else:
            shutil.copyfile(source_path, destination_path)
            _add_m4a_metadata(
                destination_path,
                title=title,
                artists=artists_text,
                album=album_name,
                year=release_year,
                lyrics=lyrics,
                artwork=artwork,
                artwork_url=artwork_url,
            )
            media_type = "audio/mp4"
    except HTTPException:
        if destination_path:
            with suppress(OSError):
                os.remove(destination_path)
        raise
    except (OSError, requests.RequestException, ValueError) as exc:
        if destination_path:
            with suppress(OSError):
                os.remove(destination_path)
        logger.exception("Download processing failed")
        raise HTTPException(status_code=502, detail="Unable to prepare this download") from exc
    finally:
        with suppress(OSError):
            os.remove(source_path)
    filename = _sanitize_filename(f"{title} - {artists_text}" if artists_text else title)
    background_tasks.add_task(os.remove, destination_path)
    return FileResponse(
        path=destination_path,
        media_type=media_type,
        filename=f"{filename}.{chosen_format}",
        background=background_tasks,
    )


@app.get("/subtitles.srt", tags=["downloads"])
def subtitles(query: str | None = Query(default=None)) -> PlainTextResponse:
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="A song ID or JioSaavn song URL is required")
    song = jiosaavn.get_song(_song_id_from_query(query.strip()), include_lyrics=True)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    subtitles_text = _lyrics_to_srt((song.get("lyrics") or "").strip())
    if not subtitles_text:
        raise HTTPException(status_code=404, detail="Lyrics are not available for this song")
    title = song.get("song") or song.get("title") or "lyrics"
    artists = song.get("primary_artists") or song.get("singers") or ""
    filename = _sanitize_filename(f"{title} - {artists}" if artists else title)
    return PlainTextResponse(
        content=subtitles_text,
        media_type="application/x-subrip",
        headers={"Content-Disposition": f'attachment; filename="{filename}.srt"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5100, reload=True)
