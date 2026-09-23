from __future__ import annotations

import json
import re
import subprocess
from collections import deque
from pathlib import Path
from typing import Callable

from .config import settings
from .control import JobControl, run_managed_process
from .hardware import detect_hardware


class VideoValidationError(ValueError):
    pass


def probe_video(path: Path) -> dict[str, float | int | str | None]:
    command = [
        settings.ffprobe_bin,
        "-v", "error",
        "-show_entries", "stream=index,codec_type,width,height,codec_name:format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=90)
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is not installed or not available on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise VideoValidationError("The uploaded file could not be read as a video.") from exc

    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video_stream:
        raise VideoValidationError("No video stream was found in the uploaded file.")
    try:
        duration = float(payload.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        raise VideoValidationError("Could not determine video duration.")
    if duration > settings.max_duration_seconds + 0.25:
        raise VideoValidationError(f"Video is longer than the {settings.max_duration_seconds // 60}-minute enhancement limit.")

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise VideoValidationError("Could not determine video dimensions.")

    landscape_ok = width <= settings.max_input_width and height <= settings.max_input_height
    portrait_ok = width <= settings.max_input_height and height <= settings.max_input_width
    if not (landscape_ok or portrait_ok):
        raise VideoValidationError(
            f"Input video is {width}×{height}. Enhancement accepts source videos up to 1080p (1920×1080, or portrait equivalent)."
        )

    return {
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "codec_name": video_stream.get("codec_name") or "unknown",
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
    }


def _profile(profile: str) -> dict:
    profiles = {
        "fast": {
            "x264_preset": "superfast",
            "x264_crf": settings.x264_crf_fast,
            "nvenc_preset": "p2",
            "nvenc_cq": settings.nvenc_cq_fast,
            "qsv_quality": settings.qsv_quality_fast,
            "scale": "bicubic",
        },
        "balanced": {
            "x264_preset": "faster",
            "x264_crf": settings.x264_crf_balanced,
            "nvenc_preset": "p4",
            "nvenc_cq": settings.nvenc_cq_balanced,
            "qsv_quality": settings.qsv_quality_balanced,
            "scale": "lanczos",
        },
        "quality": {
            "x264_preset": "medium",
            "x264_crf": settings.x264_crf_quality,
            "nvenc_preset": "p6",
            "nvenc_cq": settings.nvenc_cq_quality,
            "qsv_quality": settings.qsv_quality_quality,
            "scale": "lanczos",
        },
    }
    if profile not in profiles:
        raise ValueError("Speed profile must be fast, balanced, or quality.")
    return profiles[profile]


def _software_filter(target_height: int, enhancement: str, scale_algo: str) -> str:
    filters = [f"scale=-2:{target_height}:flags={scale_algo}", "setsar=1"]
    if enhancement == "medium":
        filters += ["hqdn3d=1.0:1.0:2.0:2.0", "eq=contrast=1.02:saturation=1.02", "unsharp=5:5:0.38:5:5:0.0"]
    elif enhancement == "strong":
        filters += ["hqdn3d=1.6:1.6:3.2:3.2", "eq=contrast=1.035:saturation=1.035", "unsharp=7:7:0.55:7:7:0.0"]
    elif enhancement != "light":
        raise ValueError("Enhancement must be light, medium, or strong.")
    return ",".join(filters)


def _audio_args(audio_codec: str | None) -> list[str]:
    if audio_codec in {None, "aac", "mp3"}:
        return ["-c:a", "copy"] if audio_codec else []
    return ["-c:a", "aac", "-b:a", "192k"]


def _base_output(audio_codec: str | None) -> list[str]:
    return [
        "-map", "0:v:0", "-map", "0:a?",
        *_audio_args(audio_codec),
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
    ]


def build_ffmpeg_candidates(
    input_path: Path,
    output_path: Path,
    *,
    target_height: int,
    profile: str,
    enhancement: str,
    engine: str,
    audio_codec: str | None,
    hardware: dict | None = None,
) -> list[tuple[str, list[str]]]:
    if target_height not in {1080, 1440, 2160}:
        raise ValueError("Target quality must be 1080p, 1440p, or 2160p.")
    if engine not in {"auto", "cpu", "nvidia", "qsv"}:
        raise ValueError("Engine must be auto, cpu, nvidia, or qsv.")
    p = _profile(profile)
    hardware = hardware or detect_hardware()
    if engine == "auto":
        engine = hardware.get("recommendedEngine", "cpu")

    common_in = [settings.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-nostdin"]
    tail = _base_output(audio_codec)
    candidates: list[tuple[str, list[str]]] = []

    def add(label: str, before_input: list[str], vf: str, encoder_args: list[str]) -> None:
        candidates.append((label, [
            *common_in,
            *before_input,
            "-i", str(input_path),
            "-vf", vf,
            *encoder_args,
            *tail,
            str(output_path),
        ]))

    software_vf = _software_filter(target_height, enhancement, p["scale"])
    x264 = ["-c:v", "libx264", "-preset", p["x264_preset"], "-crf", str(p["x264_crf"]), "-pix_fmt", "yuv420p"]
    nvenc = ["-c:v", "h264_nvenc", "-preset", p["nvenc_preset"], "-rc", "vbr", "-cq", str(p["nvenc_cq"]), "-b:v", "0"]
    qsv = ["-c:v", "h264_qsv", "-global_quality", str(p["qsv_quality"])]

    if engine == "nvidia":
        if hardware.get("nvencAvailable") and enhancement == "light":
            interp = "lanczos" if p["scale"] == "lanczos" else "bicubic"
            add(
                "NVIDIA CUDA DECODE/SCALE + NVENC",
                ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"],
                f"scale_cuda=-2:{target_height}:interp_algo={interp}",
                nvenc,
            )
        if hardware.get("nvencAvailable"):
            add("NVIDIA NVENC + CPU FILTERS", [], software_vf, nvenc)
        if hardware.get("cudaScaleAvailable"):
            interp = "lanczos" if p["scale"] == "lanczos" else "bicubic"
            cuda_filters = [
                "format=nv12",
                "hwupload_cuda",
                f"scale_cuda=-2:{target_height}:interp_algo={interp}",
                "hwdownload",
                "format=nv12",
                "setsar=1",
            ]
            if enhancement == "medium":
                cuda_filters += ["hqdn3d=1.0:1.0:2.0:2.0", "unsharp=5:5:0.38:5:5:0.0"]
            elif enhancement == "strong":
                cuda_filters += ["hqdn3d=1.6:1.6:3.2:3.2", "unsharp=7:7:0.55:7:7:0.0"]
            add("NVIDIA CUDA SCALE + CPU X264", [], ",".join(cuda_filters), x264)

    elif engine == "qsv":
        if hardware.get("qsvAvailable"):
            # Attempt an all-QSV path first on systems where the runtime exposes a QSV device.
            qsv_before = []
            if hardware.get("platform") == "Windows":
                qsv_before = [
                    "-init_hw_device", "qsv=hw,child_device_type=d3d11va",
                    "-filter_hw_device", "hw",
                    "-hwaccel", "qsv", "-hwaccel_output_format", "qsv",
                ]
            if enhancement == "light" and hardware.get("qsvScaleCompiled"):
                add(
                    "INTEL QSV DECODE/SCALE/ENCODE",
                    qsv_before,
                    f"scale_qsv=w=-1:h={target_height}",
                    qsv,
                )
            add("INTEL QSV ENCODE + CPU FILTERS", [], software_vf, qsv)

    # Always keep CPU as a robust final fallback, including when explicit hardware was selected.
    add("CPU X264", [], software_vf, x264)
    return candidates


def _parse_speed(value: str) -> float | None:
    match = re.match(r"([0-9.]+)x", value or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _run_candidate(
    label: str,
    command: list[str],
    output_path: Path,
    duration_seconds: float,
    report: Callable[[float, dict | None], None],
    control: JobControl,
) -> tuple[bool, str]:
    output_path.unlink(missing_ok=True)
    report(0.0, {"engineActual": label})
    # Drain FFmpeg's diagnostics with progress. A separate unread stderr pipe can
    # fill up and leave a long encode blocked while the parent waits on stdout.
    proc = run_managed_process(command, control, stderr=subprocess.STDOUT)
    metrics: dict[str, str] = {}
    diagnostics: deque[str] = deque(maxlen=40)
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            control.check()
            line = raw.strip()
            if "=" not in line:
                if line:
                    diagnostics.append(line)
                continue
            key, value = line.split("=", 1)
            if key not in {"frame", "fps", "stream_0_0_q", "bitrate", "total_size", "out_time_us", "out_time_ms", "out_time", "dup_frames", "drop_frames", "speed", "progress"}:
                diagnostics.append(line)
                continue
            metrics[key] = value
            if key == "progress":
                out_us = metrics.get("out_time_us") or metrics.get("out_time_ms")
                progress = 0.0
                if out_us:
                    try:
                        progress = min(99.5, max(0.0, float(out_us) / 1_000_000 / duration_seconds * 100))
                    except (ValueError, ZeroDivisionError):
                        progress = 0.0
                fps = None
                try:
                    fps = float(metrics.get("fps", ""))
                except ValueError:
                    pass
                realtime = _parse_speed(metrics.get("speed", ""))
                eta = None
                if realtime and realtime > 0 and progress < 100:
                    remaining_media = duration_seconds * (1 - progress / 100)
                    eta = int(remaining_media / realtime)
                patch = {"engineActual": label}
                if fps is not None:
                    patch["fps"] = round(fps, 2)
                if realtime is not None:
                    patch["realtime"] = round(realtime, 2)
                if eta is not None:
                    patch["etaSeconds"] = eta
                if metrics.get("total_size"):
                    try:
                        patch["encodedBytes"] = int(metrics["total_size"])
                    except ValueError:
                        pass
                report(progress, patch)
                metrics = {}
        returncode = proc.wait()
        control.check()
        if returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return True, ""
        return False, ("\n".join(diagnostics) or f"FFmpeg exited with code {returncode}")[-3000:]
    finally:
        control.unregister_process(proc)


def transcode(
    input_path: Path,
    output_path: Path,
    duration_seconds: float,
    report: Callable[[float, dict | None], None],
    control: JobControl,
    *,
    target_height: int = 1080,
    profile: str = "fast",
    enhancement: str = "light",
    engine: str = "auto",
    audio_codec: str | None = None,
) -> dict:
    hardware = detect_hardware()
    if engine == "qsv" and not hardware.get("qsvAvailable"):
        raise RuntimeError("Intel Quick Sync was selected but is not available to this backend. On Windows Docker Desktop, run the backend natively to expose QSV.")
    if engine == "nvidia" and not (hardware.get("nvencAvailable") or hardware.get("cudaScaleAvailable")):
        raise RuntimeError("NVIDIA acceleration was selected but FFmpeg could not initialize CUDA/NVENC.")

    candidates = build_ffmpeg_candidates(
        input_path,
        output_path,
        target_height=target_height,
        profile=profile,
        enhancement=enhancement,
        engine=engine,
        audio_codec=audio_codec,
        hardware=hardware,
    )
    errors = []
    for label, command in candidates:
        ok, error = _run_candidate(label, command, output_path, duration_seconds, report, control)
        if ok:
            report(100.0, {"engineActual": label, "etaSeconds": 0})
            return {"engineActual": label}
        errors.append(f"{label}: {error}")
        control.check()
    raise RuntimeError("All video processing engines failed. " + " | ".join(errors)[-6000:])
