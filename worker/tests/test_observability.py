from __future__ import annotations

import io
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.observability import OperationMonitor, exception_chain


class ObservabilityTests(unittest.TestCase):
    def test_sqlite_busy_and_snapshot_have_distinct_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'locks.db')
            with closing(sqlite3.connect(path, timeout=0)) as first, closing(sqlite3.connect(path, timeout=0)) as second:
                try:
                    first.execute('PRAGMA journal_mode=WAL')
                    first.execute('CREATE TABLE evidence(value INTEGER)')
                    first.execute('INSERT INTO evidence VALUES (1)')
                    first.commit()
                    first.execute('BEGIN IMMEDIATE')
                    with self.assertRaises(sqlite3.OperationalError) as busy:
                        second.execute('INSERT INTO evidence VALUES (2)')
                    self.assertEqual(exception_chain(busy.exception)[0]['sqlite_errorname'], 'SQLITE_BUSY')
                    second.rollback()
                    first.rollback()
                    first.execute('BEGIN')
                    first.execute('SELECT * FROM evidence').fetchall()
                    second.execute('INSERT INTO evidence VALUES (2)')
                    second.commit()
                    with self.assertRaises(sqlite3.OperationalError) as stale:
                        first.execute('INSERT INTO evidence VALUES (3)')
                    detail = exception_chain(stale.exception)[0]
                    self.assertEqual(detail['sqlite_errorname'], 'SQLITE_BUSY_SNAPSHOT')
                    self.assertEqual(detail['sqlite_errorcode'], sqlite3.SQLITE_BUSY_SNAPSHOT)
                    first.rollback()
                finally:
                    first.close()
                    second.close()

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "worker.db"
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        apply_migrations(connection, MIGRATIONS_DIR)
        connection.close()
        self.output = io.StringIO()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_success_persists_progress_result_and_json_logs(self) -> None:
        monitor = OperationMonitor(
            database=self.database,
            command="refresh-fundamentals",
            context={"snapshot_id": 7, "path": Path("/tmp/data")},
            output=self.output,
        )
        monitor.start()
        monitor.progress(10, 20, "processed ten", symbol="AAPL")
        monitor.result("refresh complete", refreshed=20)
        monitor.complete()
        monitor.close()

        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM operation_runs").fetchone()
        events = connection.execute(
            "SELECT event FROM operation_events ORDER BY id"
        ).fetchall()
        connection.close()
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(row["progress_current"], 10)
        self.assertEqual(json.loads(row["result_json"]), {"refreshed": 20})
        self.assertEqual(
            [event["event"] for event in events],
            [
                "operation_started",
                "operation_progress",
                "operation_result",
                "operation_succeeded",
            ],
        )
        records = [json.loads(line) for line in self.output.getvalue().splitlines()]
        self.assertTrue(all(record["operation_id"] == monitor.id for record in records))

    def test_failure_persists_exception_chain_and_traceback(self) -> None:
        monitor = OperationMonitor(
            database=self.database,
            command="test-failure",
            context={},
            output=self.output,
        )
        monitor.start()
        try:
            try:
                raise UnicodeDecodeError("utf-8", b"x", 0, 1, "fixture")
            except UnicodeDecodeError as cause:
                raise ValueError("provider returned invalid JSON") from cause
        except ValueError as error:
            monitor.fail(error)
            chain = exception_chain(error)
        finally:
            monitor.close()

        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM operation_runs").fetchone()
        connection.close()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_type"], "ValueError")
        self.assertEqual(
            [entry["type"] for entry in chain],
            ["ValueError", "UnicodeDecodeError"],
        )
        self.assertIn("The above exception was the direct cause", row["traceback"])

    def test_successful_idle_operation_can_be_discarded(self) -> None:
        monitor = OperationMonitor(
            database=self.database,
            command="work-once",
            context={},
            output=self.output,
        )
        monitor.start()
        monitor.discard_on_success()
        monitor.complete()
        monitor.close()

        connection = sqlite3.connect(self.database)
        count = connection.execute("SELECT COUNT(*) FROM operation_runs").fetchone()[0]
        connection.close()
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
