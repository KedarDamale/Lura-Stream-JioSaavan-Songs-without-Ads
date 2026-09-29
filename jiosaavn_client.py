import base64
import json
import re
from json import JSONDecodeError
from typing import Any, Dict, List, Optional, Union

import requests
from pyDes import ECB, PAD_PKCS5, des

import endpoints as endpoints


def search_for_song(query: str, include_lyrics: bool, return_songdata: bool) -> Union[List[Dict[str, Any]], Dict[str, Any], None]:
    if query.startswith("http") and ("saavn.com" in query or "jiosaavn" in query):
        song_id = get_song_id(query)
        return get_song(song_id, include_lyrics)

    search_url = endpoints.search_base_url + query
    response_text = _http_get_text(search_url)

    # Fix JSON where double quotes appear inside (From "...")
    pattern = r'\(From "([^"]+)"\)'
    response_text = re.sub(pattern, r"(From '\\1')", response_text)

    response_json = _parse_json(response_text)
    songs_data = response_json.get("songs", {}).get("data", [])
    if not return_songdata:
        return songs_data

    formatted_songs: List[Dict[str, Any]] = []
    for song in songs_data:
        song_id = song.get("id")
        if not song_id:
            continue
        song_data = get_song(song_id, include_lyrics)
        if song_data:
            formatted_songs.append(song_data)
    return formatted_songs


def get_song(song_id: str, include_lyrics: bool) -> Optional[Dict[str, Any]]:
    try:
        details_url = endpoints.song_details_base_url + song_id
        response_text = _http_get_text(details_url)
        response_json = _parse_json(response_text)
        raw_song = response_json.get(song_id)
        if not raw_song:
            return None
        return _format_song(raw_song, include_lyrics)
    except Exception:
        return None


def get_song_id(url: str) -> str:
    response_text = _http_get_text(url)
    # Try multiple patterns robustly
    patterns = [
        r'"pid":"([^"]+)"',
        r'"songid":"([^"]+)"',
        r'"type":"song"[\s\S]*?"id":"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, response_text)
        if match:
            return match.group(1)
    # Fallback: return trailing token from URL if present (may be e_songid, not always usable)
    try:
        return url.rstrip("/").split("/")[-1]
    except Exception:
        raise ValueError("Unable to extract song id from the provided URL")


def get_album(album_id: str, include_lyrics: bool) -> Optional[Dict[str, Any]]:
    try:
        url = endpoints.album_details_base_url + album_id
        response_text = _http_get_text(url)
        response_json = _parse_json(response_text)
        return _format_album(response_json, include_lyrics)
    except Exception:
        return None


def get_album_id(input_url: str) -> str:
    response_text = _http_get_text(input_url)
    try:
        return response_text.split('"album_id":"')[1].split('"')[0]
    except IndexError:
        return response_text.split('"page_id","')[1].split('","')[0]


def get_playlist(list_id: str, include_lyrics: bool) -> Optional[Dict[str, Any]]:
    try:
        url = endpoints.playlist_details_base_url + list_id
        response_text = _http_get_text(url)
        response_json = _parse_json(response_text)
        return _format_playlist(response_json, include_lyrics)
    except Exception:
        return None


def get_playlist_id(input_url: str) -> str:
    response_text = _http_get_text(input_url)
    try:
        return response_text.split('"type":"playlist","id":"')[1].split('"')[0]
    except IndexError:
        return response_text.split('"page_id","')[1].split('","')[0]


def get_lyrics(lyrics_id_or_song_id: str) -> str:
    # Try primary endpoint variant
    def _fetch(u: str) -> str:
        try:
            lyrics_json = _http_get_text(u)
            lyrics_data = _parse_json(lyrics_json)
            raw = lyrics_data.get("lyrics", "")
            if not isinstance(raw, str):
                return ""
            text = raw.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            text = re.sub(r"<[^>]+>", "", text)
            return text.strip()
        except Exception:
            return ""

    primary_url = endpoints.lyrics_base_url + lyrics_id_or_song_id
    text = _fetch(primary_url)
    if text:
        return text
    # Fallback: simplified endpoint without ctx/api_version parameters
    alt_url = f"https://www.jiosaavn.com/api.php?__call=lyrics.getLyrics&_format=json&lyrics_id={lyrics_id_or_song_id}"
    return _fetch(alt_url)


def _format_song(data: Dict[str, Any], include_lyrics: bool) -> Dict[str, Any]:
    try:
        data["media_url"] = _decrypt_url(data["encrypted_media_url"]).replace("_96.mp4", "_320.mp4")
        if data.get("320kbps") != "true":
            data["media_url"] = data["media_url"].replace("_320.mp4", "_160.mp4")
        data["media_preview_url"] = (
            data["media_url"]
            .replace("_320.mp4", "_96_p.mp4")
            .replace("_160.mp4", "_96_p.mp4")
            .replace("//aac.", "//preview.")
        )
    except (KeyError, TypeError):
        # Fallback to derive media_url from preview URL
        preview_url = data.get("media_preview_url", "")
        preview_url = preview_url.replace("preview", "aac")
        if data.get("320kbps") == "true":
            preview_url = preview_url.replace("_96_p.mp4", "_320.mp4")
        else:
            preview_url = preview_url.replace("_96_p.mp4", "_160.mp4")
        data["media_url"] = preview_url

    # Normalize selected string fields
    for field_name in [
        "song",
        "music",
        "singers",
        "starring",
        "album",
        "primary_artists",
    ]:
        if field_name in data:
            data[field_name] = _normalize_text(data.get(field_name))

    # Prefer higher-res artwork
    if "image" in data and isinstance(data["image"], str):
        data["image"] = data["image"].replace("150x150", "500x500")

    # Attach lyrics if requested; attempt fetch even if flag is missing
    if include_lyrics:
        try:
            lyrics_id = data.get("lyrics_id") or data.get("id")
            data["lyrics"] = get_lyrics(str(lyrics_id)) if lyrics_id else None
        except Exception:
            data["lyrics"] = None

    if "copyright_text" in data and isinstance(data["copyright_text"], str):
        data["copyright_text"] = data["copyright_text"].replace("&copy;", "©")

    return data


def _format_album(data: Dict[str, Any], include_lyrics: bool) -> Dict[str, Any]:
    if "image" in data and isinstance(data["image"], str):
        data["image"] = data["image"].replace("150x150", "500x500")
    for field_name in ["name", "primary_artists", "title"]:
        if field_name in data:
            data[field_name] = _normalize_text(data.get(field_name))
    if "songs" in data and isinstance(data["songs"], list):
        data["songs"] = [_format_song(song, include_lyrics) for song in data["songs"]]
    return data


def _format_playlist(data: Dict[str, Any], include_lyrics: bool) -> Dict[str, Any]:
    for field_name in ["firstname", "listname"]:
        if field_name in data:
            data[field_name] = _normalize_text(data.get(field_name))
    if "songs" in data and isinstance(data["songs"], list):
        data["songs"] = [_format_song(song, include_lyrics) for song in data["songs"]]
    return data


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return (
        value.encode().decode()
        .replace("&quot;", "'")
        .replace("&amp;", "&")
        .replace("&#039;", "'")
    )


def _decrypt_url(encrypted_url: str) -> str:
    cipher = des(b"38346591", ECB, b"\0\0\0\0\0\0\0\0", pad=None, padmode=PAD_PKCS5)
    enc = base64.b64decode(encrypted_url.strip())
    dec = cipher.decrypt(enc, padmode=PAD_PKCS5).decode("utf-8")
    return dec


def _http_get_text(url: str, data: Optional[List[tuple]] = None) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.jiosaavn.com/",
        "Origin": "https://www.jiosaavn.com",
    }
    response = requests.get(url, params=None, data=data, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def _decode_unicode_escape(text: str) -> str:
    """Decode legacy escaped text without being used to transform JSON."""
    try:
        return text.encode("utf-8").decode("unicode-escape")
    except UnicodeDecodeError:
        return text


def _parse_json(text: str) -> Any:
    """Parse provider JSON, escaping stray backslashes in text fields safely.

    JioSaavn occasionally returns values containing sequences such as ``\\x``
    that are not legal JSON escapes. Preserve those slashes as literal text,
    while leaving valid JSON and unicode escapes untouched.
    """
    try:
        return json.loads(text)
    except JSONDecodeError:
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
        return json.loads(repaired)


