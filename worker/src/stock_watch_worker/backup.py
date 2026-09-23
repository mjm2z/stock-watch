"""Consistent, retention-bounded SQLite backups for the single-host deployment."""

from __future__ import annotations

import os
import fcntl
import json
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BackupResult:
    path: Path
    removed: tuple[Path, ...]


def create_sqlite_backup(
    database: str | Path,
    destination: str | Path,
    *,
    now: datetime | None = None,
    keep: int = 14,
    reserve_bytes: int = 5 * 1024**3,
    timeout_seconds: float = 7200,
) -> BackupResult:
    """Create and verify an online SQLite backup, then prune old managed copies."""

    if keep < 1:
        raise ValueError("backup retention must be positive")
    if reserve_bytes < 0 or timeout_seconds <= 0:
        raise ValueError("backup reserve and timeout must be valid")
    source_path = Path(database).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"database does not exist: {source_path}")
    destination_path = Path(destination).resolve()
    if destination_path == source_path or destination_path == source_path.parent:
        raise ValueError("backup destination must be separate from the database")
    destination_path.mkdir(parents=True, exist_ok=True)

    captured_at = now or datetime.now(timezone.utc)
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("backup timestamp must include a timezone")
    timestamp = captured_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final_path = destination_path / f"stock-watch-{timestamp}.db"
    temporary_path = destination_path / f".{final_path.name}.tmp"

    # The lock covers verification and pruning as well as copying.
    with (destination_path / '.backup.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('already_running: another database backup holds the lock') from exc
        return _copy(source_path, destination_path, temporary_path, final_path,
                     keep, reserve_bytes, timeout_seconds)


def _copy(source_path, destination_path, temporary_path, final_path, keep, reserve_bytes, timeout_seconds):
    started = time.monotonic()
    last_report = 0.0

    def report(phase, **details):
        print(json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(), level='info',
                              event='backup_progress', message=f'SQLite backup: {phase}',
                              phase=phase, elapsed_seconds=round(time.monotonic() - started, 1),
                              **details)), flush=True)

    source_uri = f"{source_path.as_uri()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    target = None
    completed = False
    try:
        # Pin one WAL read snapshot. Without this transaction, unrelated writers
        # can restart the incremental backup on every page batch indefinitely.
        # WAL writers remain active; release the read snapshot before verification
        # so checkpoints are not held back while checking the destination.
        if source.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'wal':
            source.execute('BEGIN')
            source.execute('SELECT count(*) FROM sqlite_schema').fetchone()
        size = source.execute('PRAGMA page_count').fetchone()[0] * source.execute('PRAGMA page_size').fetchone()[0]
        free = shutil.disk_usage(destination_path).free
        report('preflight', database_bytes=size, free_bytes=free, reserve_bytes=reserve_bytes)
        if free < size + reserve_bytes:
            raise RuntimeError(f'destination_capacity: need {size + reserve_bytes} bytes including reserve; {free} available. Previous backup preserved.')
        target = sqlite3.connect(temporary_path)

        def progress(status, remaining, total):
            nonlocal last_report
            clock = time.monotonic()
            if clock - started > timeout_seconds:
                raise TimeoutError('backup timeout during copying; previous backup preserved')
            if clock - last_report >= 30 or remaining == 0:
                free = shutil.disk_usage(destination_path).free
                if free < reserve_bytes:
                    raise RuntimeError('destination_capacity: free space fell below backup reserve')
                report('copying', pages_copied=total - remaining, pages_total=total,
                       percent=round(100 * (total - remaining) / max(total, 1), 1), free_bytes=free)
                last_report = clock

        # Journal-only progress: writing progress into the source DB would restart
        # the online backup while other connections are writing to that database.
        source.backup(target, pages=4096, progress=progress)
        source.rollback()
        report('verifying')
        last_report = time.monotonic()
        timed_out = False

        def verifying():
            nonlocal last_report, timed_out
            clock = time.monotonic()
            if clock - last_report >= 30:
                report('verifying')
                last_report = clock
            timed_out = clock - started > timeout_seconds
            return int(timed_out)

        target.set_progress_handler(verifying, 100000)
        try:
            result = target.execute("PRAGMA quick_check").fetchall()
        except sqlite3.OperationalError as exc:
            if timed_out:
                raise TimeoutError('backup timeout during verification; previous backup preserved') from exc
            raise
        if result != [("ok",)]:
            raise RuntimeError("backup failed SQLite integrity verification")
        target.set_progress_handler(None, 0)
        os.chmod(temporary_path, 0o600)
        reader = os.environ.get('STOCK_WATCH_BACKUP_READER')
        if reader:
            subprocess.run(['setfacl', '-m', f'u:{reader}:r--', str(temporary_path)], check=True)
        completed = True
    finally:
        if target is not None:
            target.close()
        source.close()
        if not completed:
            temporary_path.unlink(missing_ok=True)

    temporary_path.replace(final_path)
    backups = sorted(destination_path.glob("stock-watch-*.db"), reverse=True)
    removed: list[Path] = []
    for expired in backups[keep:]:
        expired.unlink()
        removed.append(expired)
    report('completed', backup_path=str(final_path), removed=len(removed))
    return BackupResult(path=final_path, removed=tuple(removed))
