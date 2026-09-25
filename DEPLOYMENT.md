# Web, backend, and Android deployment

The React app runs on Vercel. FFmpeg, Pillow, yt-dlp, PDFium, LibreOffice, and the queue run in a Render Docker web service. Android packages the same frontend and talks directly to that HTTPS backend. Vercel alone cannot run this long-lived, local-file processing queue; calling `/api` on a frontend-only deployment caused the old 404 errors.

## Automatic deployment

Connect `Omars64/Video_Quality_Converter` to Vercel and Render using their GitHub integrations. Vercel project: `video_quality_converter` (Vercel requires lowercase). Root directory: `frontend`; build/output configured in `frontend/vercel.json`.

Render: Docker, root `backend`, Dockerfile `./Dockerfile`, context `.`, Free plan, health `/api/ping`, auto-deploy **After CI Checks Pass**. `render.yaml` records the equivalent infrastructure configuration; it does not contain credentials.

GitHub Actions tests Python and web code, checks version consistency, and builds an installable debug APK under Actions → Test and build → Artifacts. Vercel's Git integration deploys pushes automatically and runs frontend tests during its build. Render waits for CI checks. Vercel does not wait for the separate backend/Android checks; protect `main` with required PR checks if that is desired.

For a normal update from the repository root:

```powershell
node scripts/version.mjs patch
git add .
git commit -m "Describe your changes"
git push origin main
```

Use `minor` for new compatible features and `major` for breaking changes. Do not bump twice if the agent already updated the version. `AGENTS.md` records the automatic versioning policy. The version script updates package files, backend version, Android versionName/versionCode; the footer reads the package version.

## Secure configuration

Render environment variables:

```text
VQI_APP_PASSWORD_HASH=<PBKDF2 hash, not the password>
VQI_SESSION_SECRET=<cryptographically random secret of at least 32 characters>
VQI_CORS_ORIGINS=https://videoqualityconverter.vercel.app,https://localhost
```

Generate hashes with `app.auth.hash_password()`; use a private ignored dotenv file and never commit its values. Browser sessions last eight hours and are stored per tab. Login is rate limited. All processing routes fail closed if authentication is unconfigured. `/api/ping` is public; downloads use five-minute job-scoped tickets. Optional `VQI_API_KEY` is for trusted tooling only, not required by the app UI.

The non-secret `VITE_API_BASE_URL` is set to `https://video-quality-converter-api.onrender.com` in committed `frontend/.env.production` so both Vercel and CI APK builds use the same backend. Never put passwords or session secrets in any `VITE_` variable. Keep local secrets in ignored files. The optional server override is inside collapsed Settings; ordinary users only enter the app password. To change backend hosts later, change this URL, push, and rebuild the APK.

## Free hosting limits

Render Free has 512 MB RAM and 0.1 CPU, spins down after inactivity, and has no persistent disk. Cold start can take about a minute. Files and job history can disappear after a restart or deployment; save results promptly. The configured limits are 100 MB/video, 25 MB/image-or-document batch, 250 MB/remote download, 10-minute videos, 10 pages/files, and 8 million image output pixels. Large/4K jobs can still exceed free resources. One worker and limited FFmpeg/download threads reduce memory use, not guarantee success.

Public links are supported when the source allows server-side access. Public visibility does not mean a site offers downloadable media: bot checks, sign-in requirements, regional restrictions, unavailable formats, and DRM can prevent a download. In particular, a public YouTube test video downloaded locally but YouTube required a bot check from Render's free server on 2026-09-24; YouTube MP4/MP3 cannot be guaranteed on that host. A user-supplied Reddit short link also returned HTTP 403 to the extractor and public JSON endpoint on 2026-09-25. The app reports that block clearly. The app does not bypass access controls. Only download content you are entitled to save. PDF/DOCX conversion is page-based; output DOCX contains page images, not OCR/editable source text. Documents with external links/embedded programs are rejected.

## Android

Use Java 21 and Android SDK 36. After configuring the public backend URL:

```powershell
cd frontend
npm ci
npm run android:sync
cd android
.\gradlew.bat assembleDebug
```

APK: `frontend/android/app/build/outputs/apk/debug/app-debug.apk`. This is debug-signed for direct installation/testing, not a Play Store release. Keep a stable private signing key for future production APK updates; CI debug keys can differ from local keys, requiring uninstall/reinstall. Android offers a native folder picker when a job starts, automatically saves the finished file there while the app remains open, and uses the share sheet when no folder was selected.

## Verification

```powershell
node scripts/version.mjs --check
cd frontend
npm test
npm run build
cd ../backend
.venv/Scripts/python.exe -m pytest -q tests
```

`scripts/smoke.py` exercises real HTTP uploads, queued processing, and signed result downloads. It reads signing credentials from an ignored dotenv file, never logs them, and supports `--url`, `--remote` and `--docx`. It creates only small test media in `.tools/smoke`. Run against production only with the owner's authorization. Its assertions complement, not replace, browser login/settings/download checks.
# Release 2.4.0 — downloads and audio

- Browser: prepare the job, then **Download media** opens a per-file Save As dialog using the final name/type. No folder picker, directory permission, or app confirmation dialog. Firefox/Safari and other browsers without `showSaveFilePicker` use their normal download preferences; a website cannot suppress browser-owned security prompts.
- Android: new completed jobs save to public **Downloads** while the app is open. Android 10+ uses MediaStore without storage permission. Android 7–9 requires the OS storage permission, but never a folder picker. Transfers are size-checked before publishing.
- Instagram: prefer explicit video + audio streams, use yt-dlp's final post-merge path, validate audio, convert HE-AAC to AAC-LC, and never hide failed audio processing behind HTML/video-only fallback. Old completed jobs remain old files; submit the link again after upgrading.
- YouTube: the container includes `yt-dlp-getpot-wpc` 1.1.2, Chromium and Xvfb, matching the reference downloader's token-provider approach. It tries token-capable mobile/web clients, then the default client on eligible extraction failures. It does not import a user's browser cookies or bypass private-account access. Free Render's 512 MB memory and source-side IP restrictions can still limit this route; production success must be tested, not inferred from local results.
- The Chromium token helper runs as the container's unprivileged app user with Chromium's sandbox disabled because hosted containers may not allow its namespaces. Do not expose Chromium's debugging port publicly.

Production media verification (uses the existing ignored auth file; never prints credentials):

```powershell
.\backend\.venv\Scripts\python.exe scripts/verify_download.py https://www.instagram.com/reel/DcyzQ5Agr8A
.\backend\.venv\Scripts\python.exe scripts/verify_download.py 'https://www.youtube.com/watch?v=jNQXAC9IVRw' --youtube mp4
```

Build an installable debug APK with Java 21 and Android SDK 36:

```powershell
cd frontend
npm ci
npm run android:sync
cd android
.\gradlew.bat assembleDebug
```

Output: `frontend/android/app/build/outputs/apk/debug/app-debug.apk`. This is debug-signed for sideloading, not a Play Store release. A production release needs your persistent private signing key; never commit that key or its passwords.
