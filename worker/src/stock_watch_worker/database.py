"""SQLite connection and migration helpers."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from .config import LoadedStrategy


SOURCE_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
INSTALLED_MIGRATIONS_DIR = (
    Path(sys.prefix) / "share" / "stock-watch-worker" / "migrations"
)
MIGRATIONS_DIR = (
    SOURCE_MIGRATIONS_DIR
    if SOURCE_MIGRATIONS_DIR.exists()
    else INSTALLED_MIGRATIONS_DIR
)


def connect(database: str | Path) -> sqlite3.Connection:
    path = str(database)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def apply_migrations(
    connection: sqlite3.Connection,
    migrations_dir: str | Path = MIGRATIONS_DIR,
) -> list[str]:
    directory = Path(migrations_dir)
    migration_files = sorted(directory.glob("*.sql"))
    if not migration_files:
        raise FileNotFoundError(f"no migrations found in {directory}")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        row["version"]
        for row in connection.execute("SELECT version FROM schema_migrations")
    }

    newly_applied: list[str] = []
    for migration in migration_files:
        version = migration.stem
        if version in applied:
            continue
        script = migration.read_text(encoding="utf-8")
        with connection:
            connection.executescript(script)
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
            )
        newly_applied.append(version)
    return newly_applied


def register_strategy(
    connection: sqlite3.Connection,
    strategy: LoadedStrategy,
) -> bool:
    """Register an immutable strategy, returning True when newly inserted."""

    existing = connection.execute(
        "SELECT config_sha256 FROM strategy_versions WHERE id = ?", (strategy.id,)
    ).fetchone()
    if existing:
        if existing["config_sha256"] != strategy.sha256:
            raise ValueError(
                f"strategy {strategy.id} is immutable; create a new version id"
            )
        return False

    with connection:
        connection.execute(
            """
            INSERT INTO strategy_versions(
                id, name, status, config_json, config_sha256
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                strategy.id,
                strategy.name,
                strategy.status,
                strategy.canonical_json,
                strategy.sha256,
            ),
        )
    return True
