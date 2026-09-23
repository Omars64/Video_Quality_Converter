from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable

import psutil


class JobStopped(RuntimeError):
    pass


class JobCancelled(RuntimeError):
    pass


@dataclass
class ProcessSnapshot:
    pid: int | None = None
    paused: bool = False


class JobControl:
    """Per-job cooperative control plus process-tree suspension/termination."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self._pause = threading.Event()
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    @property
    def paused(self) -> bool:
        return self._pause.is_set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled("Job cancelled.")
        if self._stop.is_set():
            raise JobStopped("Job stopped.")
        while self._pause.is_set():
            if self._cancel.is_set():
                raise JobCancelled("Job cancelled.")
            if self._stop.is_set():
                raise JobStopped("Job stopped.")
            time.sleep(0.15)

    def register_process(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._process = process
            if self._pause.is_set():
                self._suspend_tree(process.pid)
            if self._cancel.is_set() or self._stop.is_set():
                self._terminate_tree(process.pid)

    def unregister_process(self, process: subprocess.Popen | None = None) -> None:
        with self._lock:
            if process is None or self._process is process:
                self._process = None

    def pause(self) -> None:
        self._pause.set()
        with self._lock:
            if self._process and self._process.poll() is None:
                self._suspend_tree(self._process.pid)

    def resume(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is None:
                self._resume_tree(self._process.pid)
        self._pause.clear()

    def stop(self) -> None:
        self._stop.set()
        self._pause.clear()
        with self._lock:
            if self._process and self._process.poll() is None:
                self._terminate_tree(self._process.pid)

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.clear()
        with self._lock:
            if self._process and self._process.poll() is None:
                self._terminate_tree(self._process.pid)

    @staticmethod
    def _tree(pid: int) -> list[psutil.Process]:
        try:
            parent = psutil.Process(pid)
            return parent.children(recursive=True) + [parent]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

    @classmethod
    def _suspend_tree(cls, pid: int) -> None:
        for proc in reversed(cls._tree(pid)):
            try:
                proc.suspend()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    @classmethod
    def _resume_tree(cls, pid: int) -> None:
        for proc in cls._tree(pid):
            try:
                proc.resume()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    @classmethod
    def _terminate_tree(cls, pid: int) -> None:
        tree = cls._tree(pid)
        for proc in tree:
            try:
                proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(tree, timeout=2)
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass


def run_managed_process(
    command: list[str],
    control: JobControl,
    *,
    cwd: str | None = None,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    creationflags = 0
    start_new_session = False
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        start_new_session = True
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=stdout,
        stderr=stderr,
        text=text,
        bufsize=1 if text else -1,
        env=env,
        creationflags=creationflags,
        start_new_session=start_new_session,
    )
    control.register_process(proc)
    return proc
