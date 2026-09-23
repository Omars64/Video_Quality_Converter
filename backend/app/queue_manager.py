from __future__ import annotations

import json
import shutil
import threading
from collections import deque
from pathlib import Path
from typing import Callable

from .config import settings
from .control import JobCancelled, JobControl, JobStopped
from .db import get_job, merge_job_details, next_queue_order, update_job

ProgressFn = Callable[[float, dict | None], None]
Runner = Callable[[ProgressFn, JobControl], dict | None]


class JobManager:
    def __init__(self, workers: int):
        self.workers = max(1, workers)
        self._queue: deque[str] = deque()
        self._runners: dict[str, Runner] = {}
        self._controls: dict[str, JobControl] = {}
        self._active: set[str] = set()
        self._condition = threading.Condition()
        self._threads: list[threading.Thread] = []
        self._shutdown = False

    def start(self) -> None:
        with self._condition:
            if self._threads:
                return
            self._shutdown = False
            for index in range(self.workers):
                thread = threading.Thread(target=self._worker, name=f"media-worker-{index + 1}", daemon=True)
                thread.start()
                self._threads.append(thread)

    def shutdown(self) -> None:
        with self._condition:
            self._shutdown = True
            for control in self._controls.values():
                control.stop()
            self._condition.notify_all()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()

    def submit(self, job_id: str, runner: Runner) -> None:
        with self._condition:
            self._runners[job_id] = runner
            self._controls.setdefault(job_id, JobControl(job_id))
            if job_id not in self._queue and job_id not in self._active:
                self._queue.append(job_id)
            update_job(job_id, status="queued", queue_order=next_queue_order(), error=None)
            self._condition.notify_all()

    def has_runner(self, job_id: str) -> bool:
        with self._condition:
            return job_id in self._runners

    def pause(self, job_id: str) -> str:
        job = get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] not in {"queued", "processing"}:
            return job["status"]
        with self._condition:
            control = self._controls.setdefault(job_id, JobControl(job_id))
            control.pause()
            update_job(job_id, status="paused")
            self._condition.notify_all()
        return "paused"

    def resume(self, job_id: str) -> str:
        job = get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] != "paused":
            return job["status"]
        with self._condition:
            control = self._controls.setdefault(job_id, JobControl(job_id))
            control.resume()
            if job_id in self._active:
                update_job(job_id, status="processing")
            else:
                if job_id not in self._runners:
                    raise RuntimeError("This paused job can no longer be resumed after a server restart.")
                if job_id not in self._queue:
                    self._queue.append(job_id)
                update_job(job_id, status="queued", queue_order=next_queue_order())
            self._condition.notify_all()
        return get_job(job_id)["status"]

    def stop(self, job_id: str) -> str:
        job = get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] not in {"queued", "processing", "paused"}:
            return job["status"]
        with self._condition:
            if job_id in self._active:
                update_job(job_id, status="stopping")
                self._controls[job_id].stop()
            else:
                update_job(job_id, status="stopped")
            self._condition.notify_all()
        return get_job(job_id)["status"]

    def restart(self, job_id: str) -> str:
        job = get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] not in {"stopped", "failed"}:
            return job["status"]
        with self._condition:
            runner = self._runners.get(job_id)
            if runner is None:
                raise RuntimeError("This job cannot be restarted after the backend process has restarted.")
            old = self._controls.get(job_id)
            if old:
                old.cancel()
            self._controls[job_id] = JobControl(job_id)
            if job_id not in self._queue:
                self._queue.append(job_id)
            self._remove_partial_output(job)
            update_job(job_id, status="queued", progress=0.0, error=None, queue_order=next_queue_order())
            self._condition.notify_all()
        return "queued"

    def cancel(self, job_id: str) -> str:
        job = get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] in {"completed", "cancelled"}:
            return job["status"]
        with self._condition:
            control = self._controls.setdefault(job_id, JobControl(job_id))
            control.cancel()
            update_job(job_id, status="cancelled", error=None)
            self._condition.notify_all()
        if job_id not in self._active:
            self._cleanup_cancelled(job)
        return "cancelled"

    def queue_positions(self) -> dict[str, int]:
        with self._condition:
            visible = []
            for job_id in self._queue:
                job = get_job(job_id)
                if job and job["status"] == "queued":
                    visible.append(job_id)
            return {job_id: index + 1 for index, job_id in enumerate(visible)}

    def _next_job(self) -> tuple[str, Runner, JobControl] | None:
        for _ in range(len(self._queue)):
            job_id = self._queue.popleft()
            job = get_job(job_id)
            if not job:
                continue
            status = job["status"]
            if status == "paused":
                self._queue.append(job_id)
                continue
            if status != "queued":
                continue
            runner = self._runners.get(job_id)
            if not runner:
                update_job(job_id, status="failed", error="Job runner is unavailable.")
                continue
            control = self._controls.setdefault(job_id, JobControl(job_id))
            self._active.add(job_id)
            return job_id, runner, control
        return None

    def _worker(self) -> None:
        while True:
            with self._condition:
                while not self._shutdown:
                    item = self._next_job()
                    if item:
                        break
                    self._condition.wait(timeout=0.5)
                else:
                    return
            job_id, runner, control = item
            if control.paused:
                with self._condition:
                    self._active.discard(job_id)
                    if job_id not in self._queue:
                        self._queue.appendleft(job_id)
                    update_job(job_id, status="paused")
                    self._condition.notify_all()
                continue
            try:
                control.check()
                update_job(job_id, status="processing", error=None)

                def report(progress: float, metrics: dict | None = None) -> None:
                    control.check()
                    job = get_job(job_id)
                    if not job:
                        raise JobCancelled("Job record was deleted.")
                    if job["status"] == "paused":
                        control.check()
                    update_job(job_id, progress=max(0.0, min(100.0, float(progress))))
                    if metrics:
                        merge_job_details(job_id, metrics)

                result = runner(report, control) or {}
                control.check()
                job = get_job(job_id)
                if not job:
                    continue
                output_value = result.get("output_path") or job.get("output_path")
                output_path = Path(output_value).resolve() if output_value else None
                if output_path is None or not output_path.exists() or not output_path.is_file():
                    raise RuntimeError("Processing finished but no output file was produced.")
                fields = {
                    "status": "completed",
                    "progress": 100.0,
                    "output_path": str(output_path),
                    "output_size_bytes": output_path.stat().st_size,
                    "error": None,
                }
                for key in ("output_name", "output_mime"):
                    if key in result:
                        fields[key] = result[key]
                update_job(job_id, **fields)
                if result.get("details"):
                    merge_job_details(job_id, result["details"])
            except JobCancelled:
                job = get_job(job_id)
                if job:
                    update_job(job_id, status="cancelled", error=None)
                    self._cleanup_cancelled(job)
            except JobStopped:
                job = get_job(job_id)
                if job:
                    self._remove_partial_output(job)
                    update_job(job_id, status="stopped", error=None)
            except Exception as exc:
                job = get_job(job_id)
                if job and job["status"] not in {"cancelled", "stopped"}:
                    self._remove_partial_output(job)
                    update_job(job_id, status="failed", error=str(exc))
            finally:
                control.unregister_process()
                with self._condition:
                    self._active.discard(job_id)
                    self._condition.notify_all()

    @staticmethod
    def _remove_partial_output(job: dict) -> None:
        raw = job.get("output_path")
        if not raw:
            return
        try:
            path = Path(raw)
            if path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                for item in path.iterdir():
                    if item.is_file():
                        item.unlink(missing_ok=True)
            elif job.get("operation") in {"youtube-mp4", "youtube-mp3", "public-media-download"}:
                # These jobs start with a pending.* placeholder, while yt-dlp and
                # the HTTP resolver choose their real filename at runtime.
                output_dir = path.parent.resolve()
                if output_dir.is_relative_to(settings.outputs_dir.resolve()) and output_dir.is_dir():
                    for item in output_dir.iterdir():
                        if item.is_file():
                            item.unlink(missing_ok=True)
        except OSError:
            pass

    @classmethod
    def _cleanup_cancelled(cls, job: dict) -> None:
        cls._remove_partial_output(job)
        raw = job.get("input_path")
        if not raw:
            return
        try:
            path = Path(raw)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)
        except OSError:
            pass
