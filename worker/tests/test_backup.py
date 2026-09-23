from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from collections import namedtuple

from stock_watch_worker.backup import create_sqlite_backup


class BackupTests(unittest.TestCase):
    def test_wal_backup_keeps_snapshot_while_another_connection_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); database=root/'source.db'
            connect=sqlite3.connect
            with connect(database) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('CREATE TABLE example(value TEXT, payload BLOB)')
                writer.execute("INSERT INTO example VALUES ('before', zeroblob(1048576))")
                writer.commit()
                writes=[]
                class ConcurrentSource(sqlite3.Connection):
                    def backup(self, target, **kwargs):
                        callback=kwargs['progress']
                        def progress(status,remaining,total):
                            if remaining and not writes:
                                writer.execute("UPDATE example SET value='after'");writer.commit()
                                writes.append(True)
                            callback(status,remaining,total)
                        super().backup(target,pages=8,progress=progress)
                def connection(path,*args,**kwargs):
                    if kwargs.get('uri'): kwargs['factory']=ConcurrentSource
                    return connect(path,*args,**kwargs)
                with patch('stock_watch_worker.backup.sqlite3.connect',side_effect=connection):
                    result=create_sqlite_backup(database,root/'backups',reserve_bytes=0)
                self.assertTrue(writes)
                self.assertEqual(writer.execute('SELECT value FROM example').fetchone()[0],'after')
                with connect(result.path) as restored:
                    self.assertEqual(restored.execute('SELECT value FROM example').fetchone()[0],'before')
                    self.assertEqual(restored.execute('PRAGMA quick_check').fetchone()[0],'ok')

    def test_insufficient_space_preserves_previous_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / 'source.db'
            with sqlite3.connect(db) as connection:
                connection.execute('CREATE TABLE example(value)')
            previous = create_sqlite_backup(db, root / 'backups', reserve_bytes=0)
            original = previous.path.read_bytes()
            usage = namedtuple('usage', 'total used free')(100, 99, 1)
            with patch('stock_watch_worker.backup.shutil.disk_usage', return_value=usage):
                with self.assertRaisesRegex(RuntimeError, 'destination_capacity'):
                    create_sqlite_backup(db, root / 'backups', keep=1)
            self.assertEqual(previous.path.read_bytes(), original)
            self.assertEqual([p.resolve() for p in (root / 'backups').glob('*.db')], [previous.path])
            self.assertFalse(list((root / 'backups').glob('.*.tmp')))

    def test_copy_timeout_removes_partial_and_preserves_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / 'source.db'
            with sqlite3.connect(db) as connection:
                connection.execute('CREATE TABLE example(value)')
            previous = create_sqlite_backup(db, root / 'backups', reserve_bytes=0)
            with patch('stock_watch_worker.backup.time.monotonic', side_effect=[0, 0, 100]):
                with self.assertRaisesRegex(TimeoutError, 'timeout'):
                    create_sqlite_backup(db, root / 'backups', keep=1, reserve_bytes=0, timeout_seconds=1)
            self.assertTrue(previous.path.exists())
            self.assertFalse(list((root / 'backups').glob('.*.tmp')))

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
