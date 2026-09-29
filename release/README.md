# Release outputs

This directory is the local destination for build artifacts and is intentionally kept out of Git.

- `lura.apk` is generated with `docker build --target artifact --output type=local,dest=release -f mobile/Dockerfile mobile`.
- `lura-ios-unsigned.zip` is produced by the macOS release workflow. It is useful for QA/archive work, but iOS devices require an Apple-signed IPA for installation.

Set `LURA_API_BASE_URL` to the public HTTPS URL of the Lura server when building a mobile release. The Android emulator default is `http://10.0.2.2:5100`; a physical phone must use a reachable LAN or public server address.
