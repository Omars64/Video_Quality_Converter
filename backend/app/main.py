from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import mimetypes
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .config import settings
from .auth import router as auth_router, signing_key, valid_session
from .version import VERSION
from .db import create_job, delete_job_row, get_job, init_db, list_expired_jobs, list_jobs, mark_interrupted_jobs_failed
from .downloads import (
    RemoteDownloadError,
    download_public_media,
    download_youtube,
    inspect_youtube,
    safe_filename,
    validate_public_url,
    validate_youtube_url,
)
from .hardware import detect_hardware
from .images import FORMAT_EXTENSIONS, FORMAT_MIMES, ImageValidationError, convert_images, enhance_image, probe_image
from .documents import convert_sources, validate_source
from .queue_manager import JobManager
from .video import VideoValidationError, probe_video, transcode

manager = JobManager(settings.worker_count)


class YouTubeInspectRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


class YouTubeDownloadRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)
    outputType: str = Field(default="mp4", pattern="^(mp4|mp3)$")
    quality: str = Field(default="best", max_length=16)
    audioQuality: str = Field(default="192", pattern="^(128|192|256|320)$")
    title: str | None = Field(default=None, max_length=300)
    album: str | None = Field(default=None, max_length=300)


class RemoteDownloadRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


def _managed_path(value: str | None) -> Path | None:
    if not value:
        return None
    try:
        path = Path(value).resolve()
        root = settings.data_dir.resolve()
        if not path.is_relative_to(root):
            return None
        return path
    except (OSError, RuntimeError, ValueError):
        return None


def _remove_managed_path(value: str | None) -> None:
    path = _managed_path(value)
    if path is None or not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _job_details(job: dict) -> dict:
    raw = job.get("details_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def _public_job(job: dict, queue_positions: dict[str, int] | None = None) -> dict:
    queue_positions = queue_positions or {}
    return {
        "id": job["id"],
        "status": job["status"],
        "progress": round(float(job.get("progress") or 0), 1),
        "kind": job.get("kind") or "media",
        "operation": job.get("operation") or "process",
        "originalName": job.get("original_name") or "media",
        "durationSeconds": job.get("duration_seconds"),
        "width": job.get("width"),
        "height": job.get("height"),
        "inputSizeBytes": job.get("input_size_bytes"),
        "outputSizeBytes": job.get("output_size_bytes"),
        "outputName": job.get("output_name"),
        "outputMime": job.get("output_mime"),
        "details": _job_details(job),
        "error": job.get("error"),
        "queuePosition": queue_positions.get(job["id"]),
        "createdAt": job["created_at"],
        "updatedAt": job["updated_at"],
        "downloadUrl": f"/api/jobs/{job['id']}/download" if job["status"] == "completed" else None,
    }


def _cleanup_expired_jobs() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.retention_hours)
    for job in list_expired_jobs(cutoff.isoformat()):
        _remove_managed_path(job.get("input_path"))
        _remove_managed_path(job.get("output_path"))
        delete_job_row(job["id"])


def _startup_cleanup() -> None:
    mark_interrupted_jobs_failed()
    _cleanup_expired_jobs()


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        await asyncio.to_thread(_cleanup_expired_jobs)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    await asyncio.to_thread(_startup_cleanup)
    manager.start()
    janitor = asyncio.create_task(_retention_loop())
    try:
        yield
    finally:
        janitor.cancel()
        try:
            await janitor
        except asyncio.CancelledError:
            pass
        manager.shutdown()


app = FastAPI(title="Media Forge API", version=VERSION, lifespan=lifespan)
app.include_router(auth_router)


def _download_signature(job_id: str, expires: int) -> str:
    payload = f"{job_id}:{expires}".encode()
    return hmac.new(signing_key(), payload, hashlib.sha256).hexdigest()


def _valid_download_ticket(job_id: str, expires_raw: str | None, signature: str | None) -> bool:
    if not expires_raw or not signature:
        return False
    try:
        expires = int(expires_raw)
    except ValueError:
        return False
    now = int(time.time())
    return now <= expires <= now + 300 and hmac.compare_digest(signature, _download_signature(job_id, expires))


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if not request.url.path.startswith("/api/") or request.method == "OPTIONS" or request.url.path in {"/api/ping", "/api/auth/login"}:
        return await call_next(request)
    if not settings.api_key and (not settings.app_password_hash or len(settings.session_secret) < 32):
        return JSONResponse({"detail": "The server is not configured yet. Please contact the app owner."}, status_code=503)
    bearer = request.headers.get("authorization", "")
    token = bearer[7:] if bearer.startswith("Bearer ") else ""
    if token and (valid_session(token) or (settings.api_key and hmac.compare_digest(token, settings.api_key))):
        return await call_next(request)
    parts = request.url.path.split("/")
    if len(parts) == 5 and parts[1:3] == ["api", "jobs"] and parts[4] == "download" and request.method == "GET":
        if _valid_download_ticket(parts[3], request.query_params.get("expires"), request.query_params.get("token")):
            return await call_next(request)
    return JSONResponse({"detail": "Please sign in to continue."}, status_code=401)


# CORS must wrap authentication too, so browsers can read 401/503 responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/ping")
def ping() -> dict:
    return {"status": "ok", "version": VERSION}


@app.get("/api/health")
def health(refresh_hardware: bool = Query(False)) -> dict:
    try:
        yt_dlp_version = package_version("yt-dlp")
        yt_dlp_available = True
    except PackageNotFoundError:
        yt_dlp_version = None
        yt_dlp_available = False
    hardware = detect_hardware(refresh=refresh_hardware)
    return {
        "status": "ok",
        "version": VERSION,
        "maxDurationSeconds": settings.max_duration_seconds,
        "maxInputResolution": "1080p",
        "workerCount": settings.worker_count,
        "ffmpeg": hardware["ffmpeg"],
        "ffprobe": hardware["ffprobe"],
        "aria2": bool(shutil.which("aria2c")),
        "deno": bool(shutil.which("deno")),
        "ytDlp": yt_dlp_available,
        "ytDlpVersion": yt_dlp_version,
        "hardware": hardware,
        "features": [
            "video-enhance", "photo-enhance", "image-convert", "youtube-mp4", "youtube-mp3",
            "public-media-download", "pause-resume-stop-cancel", "multi-item-queue", "save-as",
            "nvidia-cuda", "intel-qsv-native-windows",
        ],
    }


async def _write_upload(upload: UploadFile, destination: Path, max_bytes: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with destination.open("wb") as handle:
            while chunk := await upload.read(settings.chunk_size_bytes):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail="Uploaded file is larger than the configured limit.")
                handle.write(chunk)
        return written
    finally:
        await upload.close()


@app.post("/api/video/enhance", status_code=202)
async def create_video_enhancement_job(
    file: UploadFile = File(...),
    target_height: int = Form(1080),
    profile: str = Form("fast"),
    enhancement: str = Form("light"),
    engine: str = Form("auto"),
) -> dict:
    if target_height not in {1080, 1440, 2160}:
        raise HTTPException(status_code=400, detail="Target must be 1080p, 1440p, or 2160p.")
    if profile not in {"fast", "balanced", "quality"}:
        raise HTTPException(status_code=400, detail="Speed profile must be fast, balanced, or quality.")
    if enhancement not in {"light", "medium", "strong"}:
        raise HTTPException(status_code=400, detail="Enhancement must be light, medium, or strong.")
    if engine not in {"auto", "cpu", "nvidia", "qsv"}:
        raise HTTPException(status_code=400, detail="Engine must be Auto, CPU, NVIDIA, or Intel QSV.")

    original_name = safe_filename(file.filename, "video.mp4")
    extension = Path(original_name).suffix.lower()
    if extension not in settings.allowed_video_extension_set:
        raise HTTPException(status_code=415, detail=f"Unsupported video type: {extension or 'unknown'}")

    job_id = uuid.uuid4().hex
    input_path = settings.uploads_dir / f"{job_id}{extension}"
    output_name = f"{Path(original_name).stem}_{target_height}p_enhanced.mp4"
    output_path = settings.outputs_dir / f"{job_id}_{target_height}p.mp4"
    try:
        input_size = await _write_upload(file, input_path, settings.max_upload_bytes)
        metadata = await asyncio.to_thread(probe_video, input_path)
        create_job({
            "id": job_id,
            "status": "queued",
            "kind": "video",
            "operation": "enhance",
            "original_name": original_name,
            "input_path": str(input_path),
            "output_path": str(output_path),
            "output_name": output_name,
            "output_mime": "video/mp4",
            "duration_seconds": metadata["duration_seconds"],
            "width": metadata["width"],
            "height": metadata["height"],
            "input_size_bytes": input_size,
            "details": {
                "targetHeight": target_height,
                "profile": profile,
                "enhancement": enhancement,
                "engineSelected": engine,
                "engineActual": "Queued",
            },
        })

        def runner(report, control):
            result = transcode(
                input_path,
                output_path,
                float(metadata["duration_seconds"]),
                report,
                control,
                target_height=target_height,
                profile=profile,
                enhancement=enhancement,
                engine=engine,
                audio_codec=metadata.get("audio_codec"),
            )
            return {"details": result}

        manager.submit(job_id, runner)
        return _public_job(get_job(job_id), manager.queue_positions())
    except VideoValidationError as exc:
        input_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        input_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        input_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Could not create video enhancement job: {exc}") from exc


@app.post("/api/photo/enhance", status_code=202)
async def create_photo_enhancement_job(
    file: UploadFile = File(...),
    scale: int = Form(2),
    strength: str = Form("natural"),
    output_format: str = Form("jpg"),
) -> dict:
    if scale not in {1, 2, 4}:
        raise HTTPException(status_code=400, detail="Photo scale must be 1x, 2x, or 4x.")
    if strength not in {"natural", "strong"}:
        raise HTTPException(status_code=400, detail="Photo enhancement must be natural or strong.")
    output_format = output_format.lower().replace("jpeg", "jpg")
    if output_format not in {"jpg", "png", "webp"}:
        raise HTTPException(status_code=400, detail="Photo output must be JPG, PNG, or WebP.")

    original_name = safe_filename(file.filename, "photo.jpg")
    extension = Path(original_name).suffix.lower()
    if extension not in settings.allowed_image_extension_set:
        raise HTTPException(status_code=415, detail=f"Unsupported image type: {extension or 'unknown'}")
    job_id = uuid.uuid4().hex
    input_path = settings.uploads_dir / f"{job_id}{extension}"
    output_name = f"{Path(original_name).stem}_enhanced{FORMAT_EXTENSIONS[output_format]}"
    output_path = settings.outputs_dir / f"{job_id}{FORMAT_EXTENSIONS[output_format]}"
    try:
        input_size = await _write_upload(file, input_path, settings.max_image_upload_bytes)
        metadata = await asyncio.to_thread(probe_image, input_path)
        create_job({
            "id": job_id, "status": "queued", "kind": "image", "operation": "photo-enhance",
            "original_name": original_name, "input_path": str(input_path), "output_path": str(output_path),
            "output_name": output_name, "output_mime": FORMAT_MIMES[output_format],
            "width": metadata["width"], "height": metadata["height"], "input_size_bytes": input_size,
            "details": {"scale": scale, "strength": strength, "outputFormat": output_format},
        })

        def runner(report, control):
            def progress(value: float) -> None:
                control.check()
                report(value, None)
            enhance_image(input_path, output_path, scale, strength, output_format, progress)
            return {}

        manager.submit(job_id, runner)
        return _public_job(get_job(job_id), manager.queue_positions())
    except ImageValidationError as exc:
        input_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        input_path.unlink(missing_ok=True)
        raise


@app.post("/api/images/convert", status_code=202)
async def create_image_conversion_job(
    files: list[UploadFile] = File(...),
    output_format: str = Form("pdf"),
) -> dict:
    output_format = output_format.lower().replace("jpeg", "jpg")
    if output_format not in FORMAT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Output must be PDF, DOCX, JPG, PNG, WebP, BMP, or TIFF.")
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one image.")
    if len(files) > settings.max_image_files:
        raise HTTPException(status_code=400, detail=f"A maximum of {settings.max_image_files} images can be processed at once.")

    job_id = uuid.uuid4().hex
    input_dir = settings.uploads_dir / job_id
    input_dir.mkdir(parents=True, exist_ok=True)
    input_paths: list[Path] = []
    total_size = 0
    try:
        for index, upload in enumerate(files):
            original_name = safe_filename(upload.filename, f"image-{index + 1}.jpg")
            extension = Path(original_name).suffix.lower()
            if extension not in settings.allowed_image_extension_set | {".pdf", ".docx"}:
                raise HTTPException(status_code=415, detail=f"Unsupported file type: {extension or 'unknown'}")
            path = input_dir / f"{index + 1:03d}-{original_name}"
            size = await _write_upload(upload, path, max(1, settings.max_image_upload_bytes - total_size))
            total_size += size
            if total_size > settings.max_image_upload_bytes:
                raise HTTPException(status_code=413, detail="Combined image upload is larger than the configured limit.")
            await asyncio.to_thread(validate_source, path)
            input_paths.append(path)

        first_name = Path(input_paths[0].name.split("-", 1)[-1]).stem
        if output_format == "pdf":
            output_name, output_path, output_mime = f"{first_name}_merged.pdf", settings.outputs_dir / f"{job_id}.pdf", FORMAT_MIMES["pdf"]
        elif output_format == "docx":
            output_name, output_path, output_mime = f"{first_name}_images.docx", settings.outputs_dir / f"{job_id}.docx", FORMAT_MIMES["docx"]
        elif len(input_paths) > 1 or any(path.suffix.lower() in {".pdf", ".docx"} for path in input_paths):
            output_name, output_path, output_mime = f"converted_{output_format}.zip", settings.outputs_dir / f"{job_id}_{output_format}.zip", "application/zip"
        else:
            output_name = f"{first_name}{FORMAT_EXTENSIONS[output_format]}"
            output_path = settings.outputs_dir / f"{job_id}{FORMAT_EXTENSIONS[output_format]}"
            output_mime = FORMAT_MIMES[output_format]

        create_job({
            "id": job_id, "status": "queued", "kind": "document" if output_format in {"pdf", "docx"} else "image",
            "operation": "convert", "original_name": input_paths[0].name.split("-", 1)[-1],
            "input_path": str(input_dir), "output_path": str(output_path), "output_name": output_name,
            "output_mime": output_mime, "input_size_bytes": total_size,
            "details": {"fileCount": len(input_paths), "outputFormat": output_format},
        })

        def runner(report, control):
            def progress(value: float) -> None:
                control.check()
                report(value, None)
            convert_sources(input_paths, output_path, output_format, progress, control)
            return {}

        manager.submit(job_id, runner)
        return _public_job(get_job(job_id), manager.queue_positions())
    except ImageValidationError as exc:
        shutil.rmtree(input_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        shutil.rmtree(input_dir, ignore_errors=True)
        raise


@app.post("/api/youtube/inspect")
async def inspect_youtube_video(payload: YouTubeInspectRequest) -> dict:
    try:
        return await asyncio.to_thread(inspect_youtube, payload.url)
    except RemoteDownloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/youtube/download", status_code=202)
def create_youtube_download_job(payload: YouTubeDownloadRequest) -> dict:
    try:
        validate_youtube_url(payload.url)
    except RemoteDownloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = uuid.uuid4().hex
    output_dir = settings.outputs_dir / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_type = payload.outputType.lower()
    create_job({
        "id": job_id, "status": "queued", "kind": "audio" if output_type == "mp3" else "video",
        "operation": f"youtube-{output_type}", "original_name": payload.title or "YouTube media",
        "input_path": str(output_dir), "output_path": str(output_dir / f"pending.{output_type}"),
        "output_name": f"youtube.{output_type}", "output_mime": "audio/mpeg" if output_type == "mp3" else "video/mp4",
        "details": {
            "outputType": output_type, "quality": payload.quality, "audioQuality": payload.audioQuality,
            "title": payload.title, "album": payload.album,
        },
    })

    def runner(report, control):
        path, name, mime = download_youtube(
            payload.url, output_dir, output_type, payload.quality, payload.audioQuality,
            payload.title, payload.album, report, control,
        )
        return {"output_path": str(path), "output_name": name, "output_mime": mime}

    manager.submit(job_id, runner)
    return _public_job(get_job(job_id), manager.queue_positions())


@app.post("/api/remote/download", status_code=202)
def create_remote_download_job(payload: RemoteDownloadRequest) -> dict:
    try:
        validate_public_url(payload.url)
    except RemoteDownloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = uuid.uuid4().hex
    output_dir = settings.outputs_dir / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    create_job({
        "id": job_id, "status": "queued", "kind": "remote-media", "operation": "public-media-download",
        "original_name": "linked media", "input_path": str(output_dir), "output_path": str(output_dir / "pending.bin"),
        "output_name": "download", "output_mime": "application/octet-stream",
        "details": {"sourceUrl": payload.url},
    })

    def runner(report, control):
        path, name, mime = download_public_media(payload.url, output_dir, report, control)
        return {"output_path": str(path), "output_name": name, "output_mime": mime}

    manager.submit(job_id, runner)
    return _public_job(get_job(job_id), manager.queue_positions())


@app.get("/api/jobs")
def get_jobs(limit: int = Query(100, ge=1, le=500)) -> dict:
    positions = manager.queue_positions()
    jobs = [_public_job(job, positions) for job in list_jobs(limit)]
    return {
        "jobs": jobs,
        "summary": {
            "active": sum(1 for j in jobs if j["status"] in {"processing", "paused", "stopping"}),
            "queued": sum(1 for j in jobs if j["status"] == "queued"),
            "workers": settings.worker_count,
        },
    }


@app.get("/api/jobs/{job_id}")
def get_processing_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _public_job(job, manager.queue_positions())


def _control(job_id: str, action: str) -> dict:
    if not get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found.")
    try:
        if action == "pause": manager.pause(job_id)
        elif action == "resume": manager.resume(job_id)
        elif action == "stop": manager.stop(job_id)
        elif action == "start": manager.restart(job_id)
        elif action == "cancel": manager.cancel(job_id)
        else: raise ValueError(action)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job = get_job(job_id)
    return _public_job(job, manager.queue_positions())


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str) -> dict:
    return _control(job_id, "pause")


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str) -> dict:
    return _control(job_id, "resume")


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict:
    return _control(job_id, "stop")


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: str) -> dict:
    return _control(job_id, "start")


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    return _control(job_id, "cancel")


@app.get("/api/jobs/{job_id}/download")
def download_job_output(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="Processing is not complete yet.")
    output_path = _managed_path(job.get("output_path"))
    if output_path is None or not output_path.exists() or not output_path.is_file():
        raise HTTPException(status_code=410, detail="Output file has expired or is missing.")
    media_type = job.get("output_mime") or mimetypes.guess_type(output_path.name)[0] or "application/octet-stream"
    filename = safe_filename(job.get("output_name") or output_path.name, output_path.name)
    return FileResponse(output_path, media_type=media_type, filename=filename)


@app.post("/api/jobs/{job_id}/download-ticket")
def create_download_ticket(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="Processing is not complete yet.")
    expires = int(time.time()) + 300
    return {"downloadUrl": f"/api/jobs/{job_id}/download?expires={expires}&token={_download_signature(job_id, expires)}"}


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_processing_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] in {"queued", "processing", "paused", "stopping"}:
        raise HTTPException(status_code=409, detail="Stop or cancel an active job before deleting it.")
    _remove_managed_path(job.get("input_path"))
    _remove_managed_path(job.get("output_path"))
    delete_job_row(job_id)
