# Lura release outputs

The generated APK and iOS archives in this directory are local build artifacts and are ignored by Git. GitHub Actions also publishes build outputs as workflow artifacts.

## Current server

Production web app and API: <https://lura-ten.vercel.app>

The Android release should embed this URL as `LURA_API_BASE_URL`. The Vercel deployment supports music search, web playback, lyrics, and SRT export. Vercel does not bundle FFmpeg, so MP3 transcoding may be unavailable on that host.

## Build Android

```bash
docker build --target artifact --output type=local,dest=release \
  --build-arg LURA_API_BASE_URL=https://lura-ten.vercel.app \
  --file mobile/Dockerfile mobile
```

This creates `release/lura.apk`. Flutter is installed only inside the Docker image.

## Build iOS

The macOS GitHub Actions workflow creates `lura-ios-unsigned.zip`. Device installation and App Store delivery need Apple signing credentials and provisioning profiles.
