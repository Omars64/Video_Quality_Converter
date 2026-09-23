# Upgrade to Media Forge 3.2

The ZIP supplied as the baseline identified itself as **Media Forge 2.0**. This package replaces that application with 3.2.

## Docker upgrade

Back up anything you need from old completed jobs, then replace the old project files with this package.

```powershell
docker compose down
docker compose up --build -d
```

For NVIDIA Docker mode:

```powershell
docker compose down
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
```

The Compose volume is still named `media_forge_data`; Docker may retain old persisted job data. If you explicitly want a clean data volume:

```powershell
docker compose down -v
docker compose up --build -d
```

Do not run `down -v` if you still need files stored in the old volume.

## Native Windows Quick Sync

Docker Desktop on Windows may show QSV encoders compiled into FFmpeg while exposing no `/dev/dri` device, producing `Error creating a MFX session`. In that case use:

```powershell
.\setup-windows-native.ps1
.\start-windows-native.ps1
```

This runs FFmpeg on Windows rather than inside the Linux Docker backend and allows Media Forge to runtime-test Intel QSV using the Windows graphics stack.

## Major changes from the uploaded 2.0 build

- 1080p sources are accepted.
- Batch video/photo submission.
- Shared visible work queue.
- Pause / Resume / Stop / Start / Cancel.
- Fast/Balanced/Quality processing profiles.
- Auto / CPU / NVIDIA / Intel QSV engine selection.
- Runtime hardware probes rather than compile-only checks.
- MX330 CUDA-scale path no longer incorrectly forces CUDA hardware decoding.
- YouTube MP4 and MP3 modes.
- MP3 bitrate, title, and album fields.
- Faster concurrent downloads.
- General public webpage/media resolver.
- Save As destination picker.
- Docker NVIDIA override.
- Native Windows QSV scripts.
