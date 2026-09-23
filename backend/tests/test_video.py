from pathlib import Path
import sys

from app.control import JobControl
from app.video import build_ffmpeg_candidates
from app.video import _run_candidate


def cpu_hardware():
    return {
        "platform": "Linux",
        "recommendedEngine": "cpu",
        "nvencAvailable": False,
        "cudaScaleAvailable": False,
        "qsvAvailable": False,
        "qsvScaleCompiled": False,
    }


def test_cpu_fast_command_targets_selected_height():
    candidates = build_ffmpeg_candidates(
        Path("input.mp4"), Path("output.mp4"), target_height=1440,
        profile="fast", enhancement="light", engine="cpu", audio_codec="aac", hardware=cpu_hardware(),
    )
    label, command = candidates[0]
    joined = " ".join(command)
    assert label == "CPU X264"
    assert "scale=-2:1440:flags=bicubic" in joined
    assert "-preset superfast" in joined
    assert "-c:a copy" in joined
    assert "-progress pipe:1" in joined


def test_cuda_scale_candidate_does_not_force_cuda_decode_on_partial_gpu():
    hardware = {
        **cpu_hardware(),
        "recommendedEngine": "nvidia",
        "cudaScaleAvailable": True,
    }
    candidates = build_ffmpeg_candidates(
        Path("input.mp4"), Path("output.mp4"), target_height=1080,
        profile="fast", enhancement="light", engine="nvidia", audio_codec="aac", hardware=hardware,
    )
    label, command = candidates[0]
    joined = " ".join(command)
    assert label == "NVIDIA CUDA SCALE + CPU X264"
    assert "hwupload_cuda" in joined
    assert "scale_cuda=-2:1080" in joined
    assert "-hwaccel cuda" not in joined
    assert "-c:v libx264" in joined


def test_qsv_candidate_is_available_when_runtime_is_available():
    hardware = {
        **cpu_hardware(),
        "platform": "Windows",
        "recommendedEngine": "qsv",
        "qsvAvailable": True,
        "qsvScaleCompiled": True,
    }
    candidates = build_ffmpeg_candidates(
        Path("input.mp4"), Path("output.mp4"), target_height=2160,
        profile="balanced", enhancement="light", engine="qsv", audio_codec="aac", hardware=hardware,
    )
    assert candidates[0][0] == "INTEL QSV DECODE/SCALE/ENCODE"
    assert "h264_qsv" in " ".join(candidates[0][1])
    assert "scale_qsv" in " ".join(candidates[0][1])
    assert candidates[-1][0] == "CPU X264"


def test_failed_encoder_drains_large_stderr_without_hanging(tmp_path):
    output = tmp_path / "missing.mp4"
    command = [sys.executable, "-c", "import sys; sys.stderr.write('x' * 200000 + '\\nfailure\\n'); sys.exit(1)"]
    ok, error = _run_candidate("test", command, output, 1, lambda *_: None, JobControl("test"))
    assert not ok
    assert "failure" in error
