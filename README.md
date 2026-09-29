# Lura

Lura is a self-hosted FastAPI music discovery service with an original Jinja web player and a Flutter Android client. Search for songs, albums, playlists, or JioSaavn links; stream tracks through Lura without server-side audio files; download a tagged MP3/M4A only when explicitly requested.

## Highlights

- Original orange-red, responsive music interface with dark and light themes
- Memory-only streaming proxy with HTTP range support for seeking
- Song, album, playlist, lyrics, SRT subtitle, and tagged-download API routes
- Mobile Flutter client that uses the same streaming API
- Docker-only Android build: Flutter never needs to be installed locally
- Pytest, Ruff, Docker, Android, and macOS iOS-archive checks in GitHub Actions

## Run the server

The production-shaped option is Docker:

```bash
docker compose up --build
```

Open [http://localhost:5100](http://localhost:5100). Interactive API documentation is at `/docs` and the liveness endpoint is `/health`.

For local Python development:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn main:app --reload --port 5100
```

Set `CORS_ALLOW_ORIGINS` to a comma-separated set of permitted frontend origins before exposing the server publicly. Use HTTPS in production.

## Streaming behavior

`GET /stream?query=<song-id>` resolves a track and forwards its audio in 64 KiB chunks. It does not write audio to disk; only ordinary server/client networking buffers are used. The endpoint forwards a browser/mobile `Range` header so seeking works. `/download` is deliberately the separate endpoint that creates a temporary tagged file, then deletes it after the response.

## Build the Android app with Docker

Set the public HTTPS address of your deployed server, then build the APK. The output is written to `release/lura.apk`.

```bash
docker build --target artifact --output type=local,dest=release \
  --build-arg LURA_API_BASE_URL=https://music.example.com \
  --file mobile/Dockerfile mobile
```

For Android emulator development the default server is `http://10.0.2.2:5100`. A physical device needs a reachable LAN or public server URL; rebuild with `LURA_API_BASE_URL` set to that URL.

## iOS

The release workflow produces an unsigned iOS app archive on a macOS GitHub runner. Installing on real iOS devices requires an Apple Developer signing certificate and provisioning profile; configure those as GitHub secrets before adapting the workflow to produce a signed IPA.

## Quality checks

```bash
ruff check .
pytest --cov
```

Every push to `main` runs API lint/tests, a production container build, and a Dockerized Android APK build. Tagging `v*` or manually dispatching **Lura release artifacts** uploads Android and iOS build outputs as GitHub Actions artifacts.

## Responsible use

Use Lura only for content you are permitted to access and download, and comply with the music provider’s terms and applicable copyright law.
