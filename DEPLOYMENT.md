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

The non-secret `VITE_API_BASE_URL` build variable must contain the actual Render HTTPS origin for both Vercel and APK builds. A committed `frontend/.env.production` may contain this public URL so CI APK builds use the same backend. Never put passwords or session secrets in any `VITE_` variable. Keep local secrets in ignored files. The optional server override is inside collapsed Settings; ordinary users only enter the app password.

## Free hosting limits

Render Free has 512 MB RAM and 0.1 CPU, spins down after inactivity, and has no persistent disk. Cold start can take about a minute. Files and job history can disappear after a restart or deployment; save results promptly. The configured limits are 100 MB/video, 25 MB/image-or-document batch, 250 MB/remote download, 10-minute videos, 10 pages/files, and 8 million image output pixels. Large/4K jobs can still exceed free resources. One worker and limited FFmpeg/download threads reduce memory use, not guarantee success.

Public links are supported when the source allows server-side access. Public visibility does not mean a site offers downloadable media: bot checks, sign-in requirements, regional restrictions, unavailable formats, and DRM can prevent a download. The app does not bypass access controls. Only download content you are entitled to save. PDF/DOCX conversion is page-based; output DOCX contains page images, not OCR/editable source text. Documents with external links/embedded programs are rejected.

## Android

Use Java 21 and Android SDK 36. After configuring the public backend URL:

```powershell
cd frontend
npm ci
npm run android:sync
cd android
.\gradlew.bat assembleDebug
```

APK: `frontend/android/app/build/outputs/apk/debug/app-debug.apk`. This is debug-signed for direct installation/testing, not a Play Store release. Keep a stable private signing key for future production APK updates; CI debug keys can differ from local keys, requiring uninstall/reinstall. Android downloads use the native share sheet to save/send completed files.

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
