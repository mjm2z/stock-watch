from __future__ import annotations

import sqlite3
import unittest
from datetime import date

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.historical_calendar import backfill_historical_calendar
from stock_watch_worker.market_calendar import MarketSession


class FakeCalendarProvider:
    def __init__(self, *, change_close: bool = False) -> None:
        self.calls: list[tuple[date, date]] = []
        self.change_close = change_close

    def get_market_calendar(
        self, *, start: date | str, end: date | str
    ) -> list[MarketSession]:
        start_date = start if isinstance(start, date) else date.fromisoformat(start)
        end_date = end if isinstance(end, date) else date.fromisoformat(end)
        self.calls.append((start_date, end_date))
        close = "15:00" if self.change_close else "16:00"
        return [
            MarketSession.from_alpaca(
                {"date": start_date.isoformat(), "open": "09:30", "close": close}
            )
        ]


class HistoricalCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)

    def tearDown(self) -> None:
        self.connection.close()

    def test_backfills_bounded_windows_and_reuses_succeeded_ingestion(self) -> None:
        provider = FakeCalendarProvider()
        first = backfill_historical_calendar(
            self.connection,
            provider=provider,
            start=date(2026, 1, 1),
            end=date(2026, 1, 3),
            window_days=2,
        )
        second = backfill_historical_calendar(
            self.connection,
            provider=provider,
            start=date(2026, 1, 1),
            end=date(2026, 1, 3),
            window_days=2,
        )

        self.assertEqual(provider.calls, [(date(2026, 1, 1), date(2026, 1, 2)), (date(2026, 1, 3), date(2026, 1, 3))])
        self.assertEqual(first.sessions_inserted, 2)
        self.assertEqual(first.logical_requests, 2)
        self.assertTrue(second.already_succeeded)
        rows = self.connection.execute(
            "SELECT trading_date, closes_at FROM market_sessions ORDER BY trading_date"
        ).fetchall()
        self.assertEqual(rows[0]["closes_at"], "2026-01-01T21:00:00Z")

    def test_rejects_changed_immutable_session_on_distinct_ingestion(self) -> None:
        backfill_historical_calendar(
            self.connection,
            provider=FakeCalendarProvider(),
            start=date(2026, 1, 1),
            end=date(2026, 1, 1),
        )
        with self.assertRaisesRegex(ValueError, "immutable market session changed"):
            backfill_historical_calendar(
                self.connection,
                provider=FakeCalendarProvider(change_close=True),
                start=date(2026, 1, 1),
                end=date(2026, 1, 2),
            )
        failed = self.connection.execute(
            "SELECT status FROM data_ingestions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(failed["status"], "failed")


if __name__ == "__main__":
    unittest.main()
