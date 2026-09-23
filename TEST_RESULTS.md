# Media Forge 3.2 validation

Validation performed in the build environment.

## Python backend

```text
python -m compileall -q app
pytest -q
13 passed
```

The tests cover image enhancement/conversion, URL safety, YouTube URL recognition, CPU/CUDA/QSV command construction, queue behavior, API-key protection, download tickets, malformed URL ports, partial-download cleanup, and FFmpeg progress with verbose stderr.

## Real FFmpeg conversion

A real synthetic H.264 640×360 source with AAC audio was processed through the new video engine:

```text
Input:  640×360 H.264 + AAC
Mode:   CPU / Fast / Light
Target: 1080p
Output: 1920×1080 H.264
Result: completed
```

The progress parser reported realtime speed/ETA and the output was verified with ffprobe.

## Job controls

A real FFmpeg job was exercised through the FastAPI queue:

```text
create -> processing
pause  -> paused
resume -> processing
stop   -> stopping -> stopped
start  -> queued
cancel -> cancelled
```

## FastAPI integration

A video was uploaded through the actual `/api/video/enhance` endpoint and completed through the background queue. `/api/jobs/{id}` reported `CPU X264` as the actual engine.

## Hardware-specific limitations of this validation environment

The build environment does not expose the user's NVIDIA MX330 or Intel UHD hardware, so physical CUDA/QSV execution cannot be validated here. The backend performs runtime probes on the user's machine and falls back automatically if a candidate FFmpeg path fails.

## Frontend and Android

`npm test` passed (3 tests), `npm run android:sync` completed the production Vite build, and Gradle `assembleDebug` produced an installable APK. The APK was installed and launched on an Android 36 emulator; its rendered interface was verified in the WebView. With no backend configured, the app shows a connection error while preserving the usable interface.

The debug APK is for direct testing. No hosted backend or real remote media transfer was available for an end-to-end mobile conversion test.
