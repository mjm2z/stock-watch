from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import timedelta, timezone

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.dispatcher import (
    dispatch_due_scans,
    latest_universe_snapshot_id,
)
from stock_watch_worker.market_calendar import MarketSession, scan_windows


class DispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'paper', '{}', 'hash', CURRENT_TIMESTAMP, NULL)"
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-01-01', 'fixture', 'old')
            """
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (2, 'sp500', '2026-07-01', 'fixture', 'new')
            """
        )
        self.connection.commit()
        self.session = MarketSession.from_alpaca(
            {"date": "2026-07-06", "open": "09:30", "close": "16:00"}
        )

    def tearDown(self) -> None:
        self.connection.close()

    def test_dispatch_is_idempotent_and_records_exchange_date(self) -> None:
        now = scan_windows([self.session])[0].scheduled_for.astimezone(timezone.utc)

        first = dispatch_due_scans(
            self.connection,
            now=now,
            sessions=[self.session],
            strategy_version_id="strategy-v0",
            universe_snapshot_id=2,
        )
        second = dispatch_due_scans(
            self.connection,
            now=now + timedelta(minutes=5),
            sessions=[self.session],
            strategy_version_id="strategy-v0",
            universe_snapshot_id=2,
        )

        self.assertEqual((first.due_windows, first.scans_created, first.jobs_created), (1, 1, 1))
        self.assertEqual((second.due_windows, second.scans_created, second.jobs_created), (1, 0, 0))
        scan = self.connection.execute("SELECT * FROM scan_runs").fetchone()
        job = self.connection.execute("SELECT * FROM job_runs").fetchone()
        self.assertEqual(scan["scan_type"], "open")
        self.assertEqual(scan["scheduled_for"], "2026-07-06T13:45:00Z")
        self.assertEqual(json.loads(job["metadata_json"])["market_date"], "2026-07-06")

    def test_does_not_dispatch_outside_grace_period(self) -> None:
        scheduled = scan_windows([self.session])[0].scheduled_for
        result = dispatch_due_scans(
            self.connection,
            now=scheduled + timedelta(minutes=21),
            sessions=[self.session],
            strategy_version_id="strategy-v0",
            universe_snapshot_id=2,
        )

        self.assertEqual(result.due_windows, 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0], 0)

    def test_selects_latest_point_in_time_universe(self) -> None:
        self.assertEqual(
            latest_universe_snapshot_id(
                self.connection, universe="sp500", effective_at="2026-06-01"
            ),
            1,
        )
        self.assertEqual(
            latest_universe_snapshot_id(
                self.connection, universe="sp500", effective_at="2026-07-06T13:45:00Z"
            ),
            2,
        )
        with self.assertRaisesRegex(ValueError, "no nasdaq"):
            latest_universe_snapshot_id(
                self.connection, universe="nasdaq", effective_at="2026-07-06"
            )


if __name__ == "__main__":
    unittest.main()
