# Web and Android deployment

Media Forge has two runtime parts. Vercel serves the React frontend from `frontend/`. FastAPI, FFmpeg, SQLite, the worker queue, and uploaded media need a separate persistent server or container host. The Android APK packages the React frontend and connects to that same FastAPI server.

## 1. Backend

Run the `backend/Dockerfile` on a host with persistent storage and FFmpeg support, or use the root `docker-compose.yml` on a server. Mount a persistent volume at `/data` and expose the API through HTTPS. Keep one backend process; the in-memory queue is not coordinated across multiple replicas.

Set at least:

```text
VQI_DATA_DIR=/data
VQI_WORKER_COUNT=1
VQI_API_KEY=<long random secret>
VQI_CORS_ORIGINS=https://<your-vercel-domain>,https://localhost
```

`https://localhost` is the origin of the packaged Android WebView. Add `http://localhost:5173` if using the Vite development server. CORS only controls browser access; `VQI_API_KEY` protects the API itself. Keep the key private and configure the backend URL and key on each device through the app's Backend connection form.

Health check: `GET /api/ping` is intentionally public for container checks. Other `/api` routes require the API key when configured. Completed output links use short lived, job scoped download tickets so browser downloads and Android sharing work without putting the API key in the URL.

## 2. Vercel frontend

Import `Omars64/Video_Quality_Converter` into Vercel with these settings:

```text
Project name: video_quality_converter
Root directory: frontend
Framework: Vite
Build command: npm run build
Output directory: dist
```

Vercel project names must be lowercase, so `video_quality_converter` is the closest valid form of the GitHub repository name. The Vercel deployment contains the user interface; it cannot run this long lived FFmpeg/SQLite queue. Open the deployed site and enter the backend's HTTPS origin and API key. Add the actual Vercel origin to `VQI_CORS_ORIGINS` on the backend.

## 3. Android APK

From `frontend/`:

```powershell
npm ci
npm run android:sync
cd android
.\gradlew.bat assembleDebug
```

Use JDK 21 or newer and an Android SDK with platform 36. The installable debug APK is `frontend/android/app/build/outputs/apk/debug/app-debug.apk`. It is signed with the local Android debug key and is suitable for direct testing, not Play Store publication. A release build needs a private signing key and release configuration. On first launch, enter the persistent backend's HTTPS origin and API key. Completed jobs are downloaded natively to the app cache and opened in Android's share sheet.

The web and Android clients need network access to the backend. A backend bound only to `127.0.0.1` on a desktop cannot be reached from another phone or from Vercel.
