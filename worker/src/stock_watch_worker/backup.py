"""Consistent, retention-bounded SQLite backups for the single-host deployment."""

from __future__ import annotations

import os
import sqlite3
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
) -> BackupResult:
    """Create and verify an online SQLite backup, then prune old managed copies."""

    if keep < 1:
        raise ValueError("backup retention must be positive")
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

    source_uri = f"{source_path.as_uri()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    target = sqlite3.connect(temporary_path)
    completed = False
    try:
        source.backup(target)
        result = target.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise RuntimeError("backup failed SQLite integrity verification")
        completed = True
    finally:
        target.close()
        source.close()
        if not completed:
            temporary_path.unlink(missing_ok=True)

    os.chmod(temporary_path, 0o600)
    temporary_path.replace(final_path)
    backups = sorted(destination_path.glob("stock-watch-*.db"), reverse=True)
    removed: list[Path] = []
    for expired in backups[keep:]:
        expired.unlink()
        removed.append(expired)
    return BackupResult(path=final_path, removed=tuple(removed))
