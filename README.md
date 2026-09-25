# Media Forge 2.2.0

Media Forge is a local-first media toolkit built with **React + Vite**, **FastAPI**, **FFmpeg**, **Pillow**, **python-docx**, and **yt-dlp**.

For Vercel, free Render hosting, automatic GitHub deployments, and Android setup, see [DEPLOYMENT.md](DEPLOYMENT.md). Version 2.2.0 uses password-only sign-in, a built-in backend connection, and collapsed appearance/advanced settings. Confirm applies color changes and closes Settings. Never put passwords or API keys in the frontend.

This package upgrades the original Media Forge 2.0 project with a hardware-aware work queue, multi-item submission, real process controls, faster downloads, YouTube MP4/MP3 modes, and native-Windows Intel Quick Sync support.

## Features

### Video enhancement
- Accepts source videos up to **1920×1080 / 1080p** (portrait equivalent also supported).
- Default duration limit: **90 minutes per video**.
- Targets: **1080p**, **1440p**, **2160p / 4K**.
- Add several videos at once; each becomes its own queue job.
- Speed profiles:
  - **Fast** — default; x264 `superfast` on CPU, fast hardware presets where available.
  - **Balanced**.
  - **Quality**.
- Enhancement levels:
  - **Light** — fastest; best for already-clean sources.
  - **Medium** — denoise + sharpen.
  - **Strong** — heavier cleanup.
- Engine selection:
  - **Auto** — recommended.
  - **CPU / x264**.
  - **NVIDIA** — full NVENC when available; otherwise CUDA scaling + CPU x264 where supported.
  - **Intel Quick Sync / QSV** — available when the backend can open a real QSV runtime session.
- FFmpeg progress reports FPS, realtime factor, ETA, encoded bytes, and the **actual** engine path used.

### Work queue + controls
Every long-running task uses the shared queue.

Statuses include:

```text
queued -> processing -> completed
           |   |   |
           |   |   +-> failed
           |   +-----> stopped -> start again
           +---------> paused -> resume

cancelled = permanently cancelled; uploaded source is cleaned up
```

Controls:
- **Pause / Resume** — suspends/resumes active FFmpeg/yt-dlp process trees where possible. Image operations pause cooperatively between processing steps.
- **Stop** — stops the active run but retains its source so **Start** can run it again from the beginning.
- **Cancel** — stops the job and removes its managed source/partial output.
- **Start / Retry** — requeues stopped/failed jobs while the same backend process still has their task definition.
- **Delete** — removes completed/failed/cancelled job files and state.

> Jobs cannot be resumed/restarted after the backend itself has restarted because their in-memory task function is intentionally not serialized. Interrupted jobs are marked failed.

### Photo enhancement
- Batch-select multiple photos; each becomes a separate queue job.
- 1× cleanup, 2× upscale, 4× upscale.
- Natural / Strong enhancement.
- JPG, PNG, WebP output.

### Image conversion / merge
- JPG, PNG, WebP, BMP, TIFF conversion.
- Multiple image conversions return a ZIP.
- Images → PDF.
- Images → Word `.docx`.
- Up to 100 images per job by default.

### YouTube
- Inspect available source video qualities.
- Download **MP4 with audio** at Best / source-specific resolutions.
- Download **MP3** at 128 / 192 / 256 / 320 kbps.
- Editable MP3 **Title** and **Album** metadata.
- Concurrent fragments enabled.
- Uses aria2 for ordinary HTTP/HTTPS transfers when aria2 is installed.
- FFmpeg merges streams/post-processes output.
- The older warning panel on the YouTube screen has been removed.

### Internet media link downloader
Paste one URL per line; each URL becomes a queue job. The resolver attempts:

1. Direct image/video/audio media response.
2. Parallel HTTP byte-range download when supported.
3. yt-dlp generic/site extractor for supported public media pages.
4. HTML discovery using OpenGraph/Twitter metadata, `<video>`, `<source>`, `<img>`, lazy-src and srcset.

This is best-effort public-media retrieval. No application can guarantee every website: authentication, DRM, signed/session URLs, CAPTCHAs, anti-bot systems, unsupported streaming mechanisms, or server policy can block downloads. Media Forge does **not** bypass those restrictions.

For server safety it also rejects localhost/private/link-local/reserved network destinations rather than turning a public deployment into an internal-network proxy.

### Save location and progress
Each tool can ask for a destination folder when a job starts. Finished files are saved there automatically while the app remains open; the queue also retains **Save file** for manual recovery. Progress rows show a measured ETA when enough progress data exists, and say when one cannot yet be calculated.

- Chrome/Edge and other browsers supporting `showDirectoryPicker()` let you choose a folder at the start. Android uses its native folder picker. Existing files are not overwritten.
- Chrome/Edge and other browsers supporting `showSaveFilePicker()` also display a destination/file-name picker for manual saves.
- The response body is streamed into the selected file instead of loading a multi-GB result into JavaScript memory.
- Browsers without these file-system APIs fall back to their normal download behavior and cannot choose a folder at job start.

---

# Recommended startup modes

## A. Docker — CPU / portable mode

```powershell
docker compose down
docker compose up --build -d
```

Open:

```text
http://localhost:5173
```

Health:

```text
http://localhost:8000/api/health?refresh_hardware=true
```

Normal later startup:

```powershell
docker compose up -d
```

## B. Docker — NVIDIA mode

Use this on Docker Desktop / Linux systems where NVIDIA GPU passthrough is configured:

```powershell
docker compose down
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
```

The override exposes:

```text
gpus: all
NVIDIA_DRIVER_CAPABILITIES=compute,utility,video
```

Then inspect:

```text
http://localhost:8000/api/health?refresh_hardware=true
```

### NVIDIA MX330 note

An MX330 can expose CUDA scaling while **NVENC is unavailable**. On that hardware, a job can legitimately show:

```text
NVIDIA CUDA SCALE + CPU X264
```

and Windows Task Manager may still show high CPU usage. That is expected: CUDA performs resize work, while x264 performs the expensive H.264 encode on the CPU.

Do not expect selecting “NVIDIA” on an MX330 to produce RTX-style full GPU transcoding.

## C. Native Windows — Intel Quick Sync mode

This is the recommended mode for the i7-10510U / Intel UHD laptop when Docker Desktop shows:

```text
/dev/dri = unavailable
h264_qsv = compiled
MFX session = cannot be created inside Docker
```

Docker Desktop can contain `h264_qsv` in FFmpeg without exposing the Intel media device. Running FastAPI/FFmpeg natively lets FFmpeg use the Windows graphics runtime instead.

### Requirements
- Python 3.11+
- Node.js 20.19+
- A Windows FFmpeg build containing `h264_qsv`
- Current Intel graphics driver
- Optional but recommended for YouTube: Deno

From PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup-windows-native.ps1
.\start-windows-native.ps1
```

Open:

```text
http://localhost:5173
```

Then refresh hardware detection:

```text
http://127.0.0.1:8000/api/health?refresh_hardware=true
```

A working Intel setup should report approximately:

```json
{
  "hardware": {
    "qsvCompiled": true,
    "qsvAvailable": true,
    "recommendedEngine": "qsv"
  }
}
```

Media Forge first attempts a QSV decode/scale/encode path for Light enhancement. If that exact FFmpeg path is not accepted by the driver/source codec, it automatically falls back to **QSV encode + CPU filters**, then finally CPU x264.

Test QSV directly with:

```powershell
.\test-windows-qsv.ps1
```

---

# Hardware selection logic

Auto ranks actual **runtime-tested** capabilities rather than trusting an encoder list:

```text
1. NVIDIA NVENC available
      -> NVIDIA
2. Intel QSV runtime available
      -> QSV
3. NVIDIA CUDA scale available
      -> NVIDIA CUDA scale + CPU encode
4. Otherwise
      -> CPU x264
```

`ffmpeg -encoders` only proves an encoder was compiled in. `/api/health?refresh_hardware=true` executes small runtime probes so the UI does not claim a hardware engine is usable when FFmpeg cannot initialize it.

---

# Useful commands

Docker status:

```powershell
docker compose ps
```

Backend logs:

```powershell
docker compose logs -f backend
```

Frontend logs:

```powershell
docker compose logs -f frontend
```

NVIDIA health check:

```powershell
nvidia-smi
```

FFmpeg QSV compile check:

```powershell
ffmpeg -hide_banner -encoders | findstr /I "qsv"
```

---

# Configuration

Environment variables use the `VQI_` prefix. Common values:

```text
VQI_WORKER_COUNT=1
VQI_MAX_DURATION_SECONDS=5400
VQI_RETENTION_HOURS=24
VQI_DIRECT_DOWNLOAD_CONNECTIONS=8
VQI_YOUTUBE_CONCURRENT_FRAGMENTS=8
VQI_API_KEY=<set a long random key before exposing the backend publicly>
```

`WORKER_COUNT=1` is intentional by default. Two CPU video encodes often compete for the same cores and make both jobs slower. Raise it only after benchmarking a machine with enough hardware capacity.

---

# Regression checklist

## Video
- [ ] 360p → 1080p Fast/Light.
- [ ] 720p → 1440p.
- [ ] 1080p → 1080p enhancement.
- [ ] 1080p → 2160p.
- [ ] Batch-select 3+ videos and confirm separate queue jobs.
- [ ] Pause an active encode; progress should stop changing.
- [ ] Resume it.
- [ ] Stop it, then Start; processing should restart from 0.
- [ ] Cancel an active job.
- [ ] On MX330 Docker, verify actual engine says CUDA scale + CPU x264 if CUDA scaling works.
- [ ] In native Windows mode, verify QSV runtime and Auto selection if supported.

## Photos / documents
- [ ] Batch queue several photo enhancements.
- [ ] Images → PDF.
- [ ] Images → DOCX.
- [ ] Multiple images → converted ZIP.

## YouTube
- [ ] Inspect qualities.
- [ ] Download MP4 with sound.
- [ ] Download MP3 128/192/256/320 kbps.
- [ ] Verify Title/Album tags in an audio player.
- [ ] Queue another YouTube job while the first one is processing.

## Internet links
- [ ] Direct MP4.
- [ ] Direct image.
- [ ] Page handled by yt-dlp generic extractor.
- [ ] Page containing an OpenGraph/video/image candidate.
- [ ] Multiple URLs pasted one-per-line.
- [ ] Confirm private IP / localhost URLs are rejected.

## Output
- [ ] Save As opens native picker in Edge/Chrome.
- [ ] Browser fallback download works.

---

## Important quality note

Changing 360p/720p to 1080p/4K does not recover detail that never existed in the original. The default path focuses on fast, high-quality resizing and cleanup. True AI super-resolution is a separate, substantially heavier GPU workload and is intentionally not forced into every long video job.
