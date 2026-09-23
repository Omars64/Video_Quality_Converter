from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .config import settings

_lock = threading.Lock()
_cache: tuple[float, dict] | None = None


def _run(args: list[str], timeout: int = 12) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _ffmpeg_text(flag: str) -> str:
    try:
        result = _run([settings.ffmpeg_bin, "-hide_banner", flag], timeout=8)
        return (result.stdout or "") + (result.stderr or "")
    except Exception:
        return ""


def _test_ffmpeg(args: list[str], suffix: str = ".mp4") -> tuple[bool, str]:
    fd, name = tempfile.mkstemp(prefix="media-forge-hw-", suffix=suffix)
    os.close(fd)
    path = Path(name)
    path.unlink(missing_ok=True)
    command = [settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", *args, str(path)]
    try:
        result = _run(command, timeout=18)
        ok = result.returncode == 0 and path.exists() and path.stat().st_size > 0
        error = (result.stderr or result.stdout or "").strip()[-1200:]
        return ok, error
    except Exception as exc:
        return False, str(exc)
    finally:
        path.unlink(missing_ok=True)


def _nvidia_name() -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        result = _run([exe, "--query-gpu=name", "--format=csv,noheader"], timeout=5)
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return names[0] if names else None
    except Exception:
        return None


def _windows_gpu_names() -> list[str]:
    if os.name != "nt":
        return []
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return []
    try:
        cmd = [
            powershell,
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ]
        result = _run(cmd, timeout=8)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def _qsv_runtime() -> tuple[bool, str]:
    # Windows: explicitly ask QSV to use D3D11VA first. Linux/native Intel can often
    # create a default MFX session when /dev/dri is present.
    candidates: list[list[str]] = []
    if os.name == "nt":
        candidates.append([
            "-init_hw_device", "qsv=hw,child_device_type=d3d11va",
            "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=10",
            "-t", "0.5", "-c:v", "h264_qsv", "-global_quality", "28",
        ])
    candidates.append([
        "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=10",
        "-t", "0.5", "-c:v", "h264_qsv", "-global_quality", "28",
    ])
    errors = []
    for args in candidates:
        ok, error = _test_ffmpeg(args)
        if ok:
            return True, ""
        if error:
            errors.append(error)
    return False, " | ".join(errors)[-1500:]


def _nvenc_runtime() -> tuple[bool, str]:
    return _test_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=10",
        "-t", "0.5", "-c:v", "h264_nvenc", "-preset", "p1", "-cq", "28",
    ])


def _cuda_scale_runtime() -> tuple[bool, str]:
    return _test_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=10",
        "-t", "0.5",
        "-vf", "format=nv12,hwupload_cuda,scale_cuda=256:144,hwdownload,format=nv12",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
    ])


def detect_hardware(refresh: bool = False) -> dict:
    global _cache
    now = time.monotonic()
    with _lock:
        if not refresh and _cache and now - _cache[0] < settings.hardware_cache_seconds:
            return dict(_cache[1])

        ffmpeg = bool(shutil.which(settings.ffmpeg_bin))
        ffprobe = bool(shutil.which(settings.ffprobe_bin))
        encoders = _ffmpeg_text("-encoders") if ffmpeg else ""
        filters = _ffmpeg_text("-filters") if ffmpeg else ""
        hwaccels = _ffmpeg_text("-hwaccels") if ffmpeg else ""

        nvenc_compiled = "h264_nvenc" in encoders
        cuda_compiled = "cuda" in hwaccels.lower() and "scale_cuda" in filters
        qsv_compiled = "h264_qsv" in encoders and "qsv" in hwaccels.lower()
        qsv_scale_compiled = "scale_qsv" in filters or "vpp_qsv" in filters

        nvidia_name = _nvidia_name()
        win_names = _windows_gpu_names()
        intel_name = next((name for name in win_names if "intel" in name.lower()), None)
        if not nvidia_name:
            nvidia_name = next((name for name in win_names if "nvidia" in name.lower()), None)

        nvenc_available = False
        nvenc_error = ""
        if nvenc_compiled:
            nvenc_available, nvenc_error = _nvenc_runtime()

        cuda_scale_available = False
        cuda_error = ""
        if cuda_compiled:
            cuda_scale_available, cuda_error = _cuda_scale_runtime()

        qsv_available = False
        qsv_error = ""
        if qsv_compiled:
            qsv_available, qsv_error = _qsv_runtime()

        if nvenc_available:
            recommended = "nvidia"
            acceleration = "nvenc"
        elif qsv_available:
            recommended = "qsv"
            acceleration = "qsv"
        elif cuda_scale_available:
            recommended = "nvidia"
            acceleration = "cuda-scale"
        else:
            recommended = "cpu"
            acceleration = "cpu"

        engines = [
            {"value": "auto", "label": f"Auto · recommended ({recommended.upper()})", "available": True},
            {"value": "cpu", "label": "CPU · x264 software", "available": True},
            {
                "value": "nvidia",
                "label": (
                    f"NVIDIA · {nvidia_name or 'CUDA/NVENC'} · full NVENC"
                    if nvenc_available
                    else f"NVIDIA · {nvidia_name or 'CUDA'} · CUDA scale + CPU encode"
                ),
                "available": bool(nvenc_available or cuda_scale_available),
            },
            {
                "value": "qsv",
                "label": f"Intel Quick Sync · {intel_name or 'QSV hardware encode'}",
                "available": qsv_available,
            },
        ]

        data = {
            "platform": platform.system(),
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "nvidiaPresent": bool(nvidia_name),
            "nvidiaName": nvidia_name,
            "nvencCompiled": nvenc_compiled,
            "nvencAvailable": nvenc_available,
            "nvencError": nvenc_error or None,
            "cudaScaleCompiled": cuda_compiled,
            "cudaScaleAvailable": cuda_scale_available,
            "cudaError": cuda_error or None,
            "intelName": intel_name,
            "qsvCompiled": qsv_compiled,
            "qsvScaleCompiled": qsv_scale_compiled,
            "qsvAvailable": qsv_available,
            "qsvError": qsv_error or None,
            "gpuAvailable": bool(nvenc_available or cuda_scale_available or qsv_available),
            "recommendedEngine": recommended,
            "acceleration": acceleration,
            "engines": engines,
        }
        _cache = (now, data)
        return dict(data)
