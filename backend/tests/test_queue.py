import time
from pathlib import Path

from app.config import settings
from app.db import create_job, get_job, init_db
from app.queue_manager import JobManager


def test_queued_job_can_pause_resume_and_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    init_db()
    output = settings.outputs_dir / "done.txt"
    create_job({
        "id": "queue-test",
        "status": "queued",
        "kind": "test",
        "operation": "test",
        "original_name": "test",
        "input_path": "",
        "output_path": str(output),
    })
    manager = JobManager(1)

    def runner(report, control):
        control.check()
        report(50, {"phase": "half"})
        output.write_text("ok")
        return {}

    manager.submit("queue-test", runner)
    assert manager.pause("queue-test") == "paused"
    assert get_job("queue-test")["status"] == "paused"
    assert manager.resume("queue-test") == "queued"
    manager.start()
    try:
        for _ in range(100):
            job = get_job("queue-test")
            if job["status"] == "completed":
                break
            time.sleep(0.02)
        assert job["status"] == "completed"
        assert output.read_text() == "ok"
    finally:
        manager.shutdown()


def test_failed_remote_job_removes_runtime_named_partials(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    output_dir = settings.outputs_dir / "remote-job"
    output_dir.mkdir(parents=True)
    partial = output_dir / "runtime-name.mp4.part"
    partial.write_bytes(b"partial")
    JobManager._remove_partial_output({
        "operation": "public-media-download",
        "output_path": str(output_dir / "pending.bin"),
    })
    assert not partial.exists()
