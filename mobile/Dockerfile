# Flutter exists only in this build container; it is not required on the host.
FROM ghcr.io/cirruslabs/flutter:stable AS android-template
WORKDIR /template
RUN flutter create --org com.kedardamale --project-name lura --platforms=android .

FROM ghcr.io/cirruslabs/flutter:stable AS builder
ARG LURA_API_BASE_URL=https://example.com
WORKDIR /app

# Generate the Android wrapper in Docker, then layer in Lura's application code.
COPY --from=android-template /template/android ./android
COPY --from=android-template /template/.metadata ./
COPY --from=android-template /template/analysis_options.yaml ./
COPY pubspec.yaml ./
COPY assets ./assets
COPY lib ./lib
COPY android ./android

RUN flutter pub get \
    && flutter build apk --release --dart-define=LURA_API_BASE_URL=${LURA_API_BASE_URL}

FROM scratch AS artifact
COPY --from=builder /app/build/app/outputs/flutter-apk/app-release.apk /lura.apk
