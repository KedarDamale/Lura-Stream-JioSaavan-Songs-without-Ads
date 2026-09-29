from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def test_health_is_available() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "lura"}


def test_home_renders_lura_brand() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Lura" in response.text
    assert "lura-mark.svg" in response.text


def test_search_requires_query() -> None:
    response = client.get("/song/")

    assert response.status_code == 400
    assert response.json()["status"] is False


def test_result_rejects_non_jiosaavn_urls() -> None:
    response = client.get("/result/", params={"query": "https://example.com/song/test"})

    assert response.status_code == 400
    assert response.json()["error"] == "Only JioSaavn URLs are supported"


@patch("main.jiosaavn.search_for_song")
def test_search_returns_provider_results(search_for_song: Mock) -> None:
    search_for_song.return_value = [{"id": "track-1", "song": "Lura song"}]

    response = client.get("/song/", params={"query": "Lura song"})

    assert response.status_code == 200
    assert response.json()[0]["id"] == "track-1"
    search_for_song.assert_called_once_with("Lura song", False, True)


@patch("main.jiosaavn.get_song")
def test_subtitles_are_created_from_lyrics(get_song: Mock) -> None:
    get_song.return_value = {
        "song": "Test song",
        "primary_artists": "Test artist",
        "lyrics": "First line\nSecond line",
    }

    response = client.get("/subtitles.srt", params={"query": "track-1"})

    assert response.status_code == 200
    assert "00:00:00,000 --> 00:00:02,000" in response.text
    assert "First line" in response.text


@patch("main.jiosaavn.get_song")
@patch("main.requests.get")
def test_stream_relays_audio_without_a_file(requests_get: Mock, get_song: Mock) -> None:
    get_song.return_value = {"id": "track-1", "media_url": "https://cdn.example/track.m4a"}
    upstream = Mock(status_code=200, headers={"Content-Type": "audio/mp4", "Content-Length": "3"})
    upstream.iter_content.return_value = [b"abc"]
    requests_get.return_value = upstream

    response = client.get("/stream", params={"query": "track-1"})

    assert response.status_code == 200
    assert response.content == b"abc"
    assert response.headers["cache-control"] == "no-store"
    upstream.close.assert_called_once()


def test_srt_timestamp_formatting() -> None:
    assert main._to_srt_timestamp(3_726_005) == "01:02:06,005"
