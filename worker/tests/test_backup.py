from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stock_watch_worker.backup import create_sqlite_backup


class BackupTests(unittest.TestCase):
    def test_creates_verified_backup_and_prunes_only_managed_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "stock-watch.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE observations(value TEXT NOT NULL)")
            connection.execute("INSERT INTO observations VALUES ('durable')")
            connection.commit()
            connection.close()
            destination = root / "backups"
            unrelated = destination / "keep-me.txt"
            destination.mkdir()
            unrelated.write_text("unrelated", encoding="utf-8")

            first = create_sqlite_backup(
                database,
                destination,
                now=datetime(2026, 8, 18, tzinfo=timezone.utc),
                keep=2,
            )
            create_sqlite_backup(
                database,
                destination,
                now=datetime(2026, 8, 19, tzinfo=timezone.utc),
                keep=2,
            )
            latest = create_sqlite_backup(
                database,
                destination,
                now=datetime(2026, 8, 20, tzinfo=timezone.utc),
                keep=2,
            )

            self.assertFalse(first.path.exists())
            self.assertTrue(latest.path.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(len(list(destination.glob("stock-watch-*.db"))), 2)
            restored = sqlite3.connect(latest.path)
            self.assertEqual(
                restored.execute("SELECT value FROM observations").fetchone()[0],
                "durable",
            )
            restored.close()

    def test_rejects_unsafe_or_invalid_backup_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "stock-watch.db"
            sqlite3.connect(database).close()
            with self.assertRaisesRegex(ValueError, "retention"):
                create_sqlite_backup(database, Path(directory) / "backups", keep=0)
            with self.assertRaisesRegex(ValueError, "separate"):
                create_sqlite_backup(database, database.parent)
            with self.assertRaisesRegex(ValueError, "timezone"):
                create_sqlite_backup(
                    database,
                    Path(directory) / "backups",
                    now=datetime(2026, 8, 20),
                )


if __name__ == "__main__":
    unittest.main()
