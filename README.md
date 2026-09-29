# Lura

Lura is a music discovery and streaming app with a FastAPI server, a server-rendered web player, and a Flutter Android client. Search JioSaavn songs, albums, and playlists, then stream them from the web or mobile app.

**Live app:** [https://lura-ten.vercel.app](https://lura-ten.vercel.app) · [API docs](https://lura-ten.vercel.app/docs) · [Health](https://lura-ten.vercel.app/health)

## Features

- Responsive Jinja web app with orange-red styling and persistent light/dark themes
- Song search and JioSaavn song, album, and playlist URL lookup
- Lyrics display and subtitle export
- In-memory audio streaming proxy with HTTP range forwarding for seeking
- Optional tagged MP3/M4A download endpoint
- Flutter mobile player using the same API and production server
- Docker deployment and Docker-only Android builds

## Run the server locally

```bash
docker compose up --build
```

Open [http://localhost:5100](http://localhost:5100). The API docs are at `/docs`, and `/health` reports service health.

For Python development:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn main:app --reload --port 5100
```

Set `CORS_ALLOW_ORIGINS` to comma-separated web origins if the mobile or web client is hosted separately. The deployed server currently serves the Jinja web app and API from the same origin.

## Streaming and downloads

`GET /stream?query=<song-id>` relays audio to the player in chunks and forwards `Range` requests for seeking. Streaming does not save a track on the server. `GET /download` is a separate explicit download route that uses temporary storage while preparing a tagged file.

The Vercel deployment includes the search, web, streaming, lyrics, subtitle, and M4A paths. Vercel’s Python runtime does not include FFmpeg, so MP3 transcoding may be unavailable there; use the included Docker deployment (which installs FFmpeg) for reliable MP3 downloads.

## Android build

The Flutter SDK stays inside Docker. Build an APK with the production API URL embedded:

```bash
docker build --target artifact --output type=local,dest=release \
  --build-arg LURA_API_BASE_URL=https://lura-ten.vercel.app \
  --file mobile/Dockerfile mobile
```

The APK is written to `release/lura.apk`. `LURA_API_BASE_URL` can be changed for local development; Android emulators reach a host machine at `http://10.0.2.2:5100`.

## iOS builds

GitHub Actions can create an unsigned iOS app archive on macOS. Installing on devices or distributing through the App Store requires Apple signing credentials and provisioning profiles.

## Development checks

```bash
ruff check .
pytest --cov
```

GitHub Actions checks API lint/tests, builds the server container, and builds the Android APK. The release workflow builds Android and an unsigned iOS archive.

## About

Lura is an independent project. It uses publicly accessible JioSaavn endpoints for catalog metadata and playback resolution. Use the app in accordance with provider terms and applicable rights.
