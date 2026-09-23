import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .config import settings

_DB_LOCK = threading.Lock()

_COLUMNS: dict[str, str] = {
    "id": "TEXT PRIMARY KEY",
    "status": "TEXT NOT NULL",
    "progress": "REAL NOT NULL DEFAULT 0",
    "kind": "TEXT NOT NULL DEFAULT 'media'",
    "operation": "TEXT NOT NULL DEFAULT 'process'",
    "original_name": "TEXT NOT NULL DEFAULT 'media'",
    "input_path": "TEXT NOT NULL DEFAULT ''",
    "output_path": "TEXT NOT NULL DEFAULT ''",
    "output_name": "TEXT",
    "output_mime": "TEXT",
    "duration_seconds": "REAL",
    "width": "INTEGER",
    "height": "INTEGER",
    "input_size_bytes": "INTEGER",
    "output_size_bytes": "INTEGER",
    "details_json": "TEXT",
    "error": "TEXT",
    "queue_order": "INTEGER",
    "created_at": "TEXT NOT NULL",
    "updated_at": "TEXT NOT NULL",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_queue_order() -> int:
    return time.time_ns()


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(settings.db_path, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                kind TEXT NOT NULL DEFAULT 'media',
                operation TEXT NOT NULL DEFAULT 'process',
                original_name TEXT NOT NULL DEFAULT 'media',
                input_path TEXT NOT NULL DEFAULT '',
                output_path TEXT NOT NULL DEFAULT '',
                output_name TEXT,
                output_mime TEXT,
                duration_seconds REAL,
                width INTEGER,
                height INTEGER,
                input_size_bytes INTEGER,
                output_size_bytes INTEGER,
                details_json TEXT,
                error TEXT,
                queue_order INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        for name, definition in _COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        conn.commit()


def create_job(job: dict[str, Any]) -> None:
    now = utc_now()
    details = job.get("details")
    values = {
        "id": job["id"],
        "status": job.get("status", "queued"),
        "progress": job.get("progress", 0),
        "kind": job.get("kind", "media"),
        "operation": job.get("operation", "process"),
        "original_name": job.get("original_name", "media"),
        "input_path": job.get("input_path", ""),
        "output_path": job.get("output_path", ""),
        "output_name": job.get("output_name"),
        "output_mime": job.get("output_mime"),
        "duration_seconds": job.get("duration_seconds"),
        "width": job.get("width"),
        "height": job.get("height"),
        "input_size_bytes": job.get("input_size_bytes"),
        "output_size_bytes": job.get("output_size_bytes"),
        "details_json": json.dumps(details, ensure_ascii=False) if details is not None else None,
        "error": job.get("error"),
        "queue_order": job.get("queue_order", next_queue_order()),
        "created_at": now,
        "updated_at": now,
    }
    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"INSERT INTO jobs ({columns}) VALUES ({placeholders})", tuple(values.values()))
        conn.commit()


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    if "details" in fields:
        fields["details_json"] = json.dumps(fields.pop("details"), ensure_ascii=False)
    fields["updated_at"] = utc_now()
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id]
    with _DB_LOCK, _connect() as conn:
        conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", values)
        conn.commit()


def merge_job_details(job_id: str, patch: dict[str, Any]) -> None:
    if not patch:
        return
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT details_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return
        try:
            details = json.loads(row[0] or "{}")
        except (TypeError, json.JSONDecodeError):
            details = {}
        details.update(patch)
        conn.execute(
            "UPDATE jobs SET details_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(details, ensure_ascii=False), utc_now(), job_id),
        )
        conn.commit()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 200) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
    return [dict(row) for row in rows]


def list_expired_jobs(cutoff: str) -> list[dict[str, Any]]:
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM jobs WHERE updated_at < ?
            AND status NOT IN ('queued', 'processing', 'paused', 'stopping')""",
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_job_row(job_id: str) -> None:
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()


def mark_interrupted_jobs_failed() -> None:
    now = utc_now()
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'failed', error = 'Server restarted while this job was active.', updated_at = ?
            WHERE status IN ('queued', 'processing', 'paused', 'stopping')
            """,
            (now,),
        )
        conn.commit()
