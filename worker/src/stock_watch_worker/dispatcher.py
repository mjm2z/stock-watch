"""Idempotently turn due exchange sessions into durable scan jobs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .market_calendar import MarketSession, due_scan_windows, utc_iso


ID_NAMESPACE = uuid.UUID("f6fbca90-d04f-4e10-89bc-6eaa441bd4d2")


@dataclass(frozen=True, slots=True)
class DispatchResult:
    due_windows: int
    scans_created: int
    jobs_created: int
    scan_run_ids: tuple[str, ...]


def latest_universe_snapshot_id(
    connection: sqlite3.Connection,
    *,
    universe: str,
    effective_at: str,
) -> int:
    row = connection.execute(
        """
        SELECT id
        FROM universe_snapshots
        WHERE universe = ? AND effective_at <= ?
        ORDER BY effective_at DESC, id DESC
        LIMIT 1
        """,
        (universe, effective_at),
    ).fetchone()
    if row is None:
        raise ValueError(f"no {universe} universe snapshot exists at {effective_at}")
    return int(row["id"])


def dispatch_due_scans(
    connection: sqlite3.Connection,
    *,
    now: datetime,
    sessions: Sequence[MarketSession],
    strategy_version_id: str,
    universe_snapshot_id: int,
    grace_period: timedelta = timedelta(minutes=20),
) -> DispatchResult:
    windows = due_scan_windows(now, sessions, grace_period=grace_period)
    scans_created = 0
    jobs_created = 0
    scan_ids: list[str] = []
    with connection:
        for window in windows:
            scheduled_for = utc_iso(window.scheduled_for)
            identity = f"{strategy_version_id}:{window.scan_type}:{scheduled_for}"
            scan_id = f"scan-{uuid.uuid5(ID_NAMESPACE, identity).hex}"
            job_id = f"job-{uuid.uuid5(ID_NAMESPACE, 'job:' + identity).hex}"
            scan_cursor = connection.execute(
                """
                INSERT OR IGNORE INTO scan_runs(
                    id, strategy_version_id, universe_snapshot_id,
                    scan_type, scheduled_for, data_cutoff, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued')
                """,
                (
                    scan_id,
                    strategy_version_id,
                    universe_snapshot_id,
                    window.scan_type,
                    scheduled_for,
                    scheduled_for,
                ),
            )
            scans_created += scan_cursor.rowcount
            actual_scan = connection.execute(
                """
                SELECT id FROM scan_runs
                WHERE strategy_version_id = ? AND scan_type = ? AND scheduled_for = ?
                """,
                (strategy_version_id, window.scan_type, scheduled_for),
            ).fetchone()
            if actual_scan is None:
                raise RuntimeError("scan run was not persisted")
            actual_scan_id = str(actual_scan["id"])
            scan_ids.append(actual_scan_id)
            metadata = json.dumps(
                {
                    "scan_run_id": actual_scan_id,
                    "scan_type": window.scan_type,
                    "market_date": window.market_session.trading_date.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            job_cursor = connection.execute(
                """
                INSERT OR IGNORE INTO job_runs(
                    id, job_type, idempotency_key, scheduled_for,
                    available_at, status, metadata_json
                ) VALUES (?, 'scan', ?, ?, ?, 'queued', ?)
                """,
                (job_id, identity, scheduled_for, scheduled_for, metadata),
            )
            jobs_created += job_cursor.rowcount
    return DispatchResult(len(windows), scans_created, jobs_created, tuple(scan_ids))
