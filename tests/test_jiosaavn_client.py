from unittest.mock import patch

import jiosaavn_client as client


def test_normalize_text_decodes_common_html_entities() -> None:
    assert client._normalize_text("Rock &amp; Roll &quot;Live&quot;") == "Rock & Roll 'Live'"


@patch("jiosaavn_client._decrypt_url", return_value="https://aac.example.com/audio_320.mp4")
def test_format_song_builds_stream_urls_and_normalizes_metadata(_decrypt_url) -> None:
    song = client._format_song(
        {
            "id": "track-1",
            "encrypted_media_url": "encoded-value",
            "320kbps": "true",
            "song": "A &amp; B",
            "primary_artists": "Artist &quot;One&quot;",
            "image": "https://images.example/150x150.jpg",
        },
        include_lyrics=False,
    )

    assert song["media_url"] == "https://aac.example.com/audio_320.mp4"
    assert song["media_preview_url"] == "https://preview.example.com/audio_96_p.mp4"
    assert song["song"] == "A & B"
    assert song["primary_artists"] == "Artist 'One'"
    assert "500x500" in song["image"]


@patch("jiosaavn_client._http_get_text")
def test_get_lyrics_strips_html(mock_get_text) -> None:
    mock_get_text.return_value = '{"lyrics":"First line<br>Second <b>line</b>"}'

    assert client.get_lyrics("track-1") == "First line\nSecond line"
