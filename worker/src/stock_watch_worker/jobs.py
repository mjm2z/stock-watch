"""SQLite-backed single-host job leasing and retry transitions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .market_calendar import utc_iso


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: str
    job_type: str
    scheduled_for: str
    attempt: int
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    requeued: int
    failed: int


def claim_next_job(
    connection: sqlite3.Connection,
    *,
    worker_id: str,
    now: datetime,
) -> ClaimedJob | None:
    if not worker_id.strip():
        raise ValueError("worker_id is required")
    timestamp = utc_iso(now)
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            """
            SELECT id, job_type, scheduled_for, attempt, metadata_json
            FROM job_runs
            WHERE status = 'queued'
              AND COALESCE(available_at, scheduled_for) <= ?
            ORDER BY COALESCE(available_at, scheduled_for), created_at, id
            LIMIT 1
            """,
            (timestamp,),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        metadata = _parse_metadata(str(row["metadata_json"]))
        cursor = connection.execute(
            """
            UPDATE job_runs
            SET status = 'running', started_at = ?, heartbeat_at = ?,
                claimed_by = ?, attempt = attempt + 1, error = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (timestamp, timestamp, worker_id, row["id"]),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return None
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return ClaimedJob(
        id=str(row["id"]),
        job_type=str(row["job_type"]),
        scheduled_for=str(row["scheduled_for"]),
        attempt=int(row["attempt"]) + 1,
        metadata=metadata,
    )


def heartbeat_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    worker_id: str,
    now: datetime,
) -> None:
    with connection:
        cursor = connection.execute(
            """
            UPDATE job_runs SET heartbeat_at = ?
            WHERE id = ? AND status = 'running' AND claimed_by = ?
            """,
            (utc_iso(now), job_id, worker_id),
        )
    if cursor.rowcount != 1:
        raise ValueError("job is not leased by this worker")


def complete_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    worker_id: str,
    now: datetime,
) -> None:
    with connection:
        cursor = connection.execute(
            """
            UPDATE job_runs
            SET status = 'succeeded', completed_at = ?, heartbeat_at = ?, error = NULL
            WHERE id = ? AND status = 'running' AND claimed_by = ?
            """,
            (utc_iso(now), utc_iso(now), job_id, worker_id),
        )
    if cursor.rowcount != 1:
        raise ValueError("job is not leased by this worker")


def fail_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    worker_id: str,
    now: datetime,
    error: str,
    retry_at: datetime | None = None,
    max_attempts: int = 3,
) -> str:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    row = connection.execute(
        "SELECT attempt FROM job_runs WHERE id = ? AND status = 'running' AND claimed_by = ?",
        (job_id, worker_id),
    ).fetchone()
    if row is None:
        raise ValueError("job is not leased by this worker")
    should_retry = retry_at is not None and int(row["attempt"]) < max_attempts
    status = "queued" if should_retry else "failed"
    with connection:
        connection.execute(
            """
            UPDATE job_runs
            SET status = ?, available_at = ?, completed_at = ?, error = ?,
                claimed_by = NULL, heartbeat_at = NULL,
                started_at = CASE WHEN ? = 'queued' THEN NULL ELSE started_at END
            WHERE id = ? AND status = 'running' AND claimed_by = ?
            """,
            (
                status,
                utc_iso(retry_at) if should_retry and retry_at else None,
                None if should_retry else utc_iso(now),
                error[:2000],
                status,
                job_id,
                worker_id,
            ),
        )
    return status


def recover_stale_jobs(
    connection: sqlite3.Connection,
    *,
    stale_before: datetime,
    max_attempts: int = 3,
) -> RecoveryResult:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    cutoff = utc_iso(stale_before)
    with connection:
        failed = connection.execute(
            """
            UPDATE job_runs
            SET status = 'failed', completed_at = ?,
                error = 'worker lease expired after maximum attempts',
                claimed_by = NULL, heartbeat_at = NULL
            WHERE status = 'running'
              AND COALESCE(heartbeat_at, started_at) < ?
              AND attempt >= ?
            """,
            (cutoff, cutoff, max_attempts),
        ).rowcount
        requeued = connection.execute(
            """
            UPDATE job_runs
            SET status = 'queued', available_at = ?, started_at = NULL,
                error = 'worker lease expired; queued for retry',
                claimed_by = NULL, heartbeat_at = NULL
            WHERE status = 'running'
              AND COALESCE(heartbeat_at, started_at) < ?
              AND attempt < ?
            """,
            (cutoff, cutoff, max_attempts),
        ).rowcount
    return RecoveryResult(requeued=requeued, failed=failed)


def _parse_metadata(value: str) -> Mapping[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("job metadata must be a JSON object")
    return parsed
