from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from stock_watch_worker.market_calendar import (
    MarketSession,
    due_scan_windows,
    scan_windows,
    utc_iso,
)


class MarketCalendarTests(unittest.TestCase):
    def test_uses_exchange_supplied_early_close_and_dst_offset(self) -> None:
        session = MarketSession.from_alpaca(
            {"date": "2026-11-27", "open": "09:30", "close": "13:00"}
        )

        windows = scan_windows([session])

        self.assertEqual(utc_iso(windows[0].scheduled_for), "2026-11-27T14:45:00Z")
        self.assertEqual(utc_iso(windows[1].scheduled_for), "2026-11-27T18:15:00Z")

    def test_dst_is_derived_from_market_timezone(self) -> None:
        winter = MarketSession.from_alpaca(
            {"date": "2026-01-05", "open": "09:30", "close": "16:00"}
        )
        summer = MarketSession.from_alpaca(
            {"date": "2026-07-06", "open": "09:30", "close": "16:00"}
        )

        self.assertEqual(utc_iso(scan_windows([winter])[0].scheduled_for), "2026-01-05T14:45:00Z")
        self.assertEqual(utc_iso(scan_windows([summer])[0].scheduled_for), "2026-07-06T13:45:00Z")

    def test_due_window_has_bounded_catchup_and_requires_aware_time(self) -> None:
        session = MarketSession.from_alpaca(
            {"date": "2026-07-06", "open": "09:30", "close": "16:00"}
        )
        scheduled = scan_windows([session])[0].scheduled_for.astimezone(timezone.utc)

        self.assertEqual(
            [window.scan_type for window in due_scan_windows(scheduled, [session])],
            ["open"],
        )
        self.assertEqual(
            len(due_scan_windows(scheduled + timedelta(minutes=19), [session])), 1
        )
        self.assertEqual(
            len(due_scan_windows(scheduled + timedelta(minutes=20), [session])), 0
        )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            due_scan_windows(datetime(2026, 7, 6, 13, 45), [session])

    def test_rejects_malformed_or_inverted_sessions(self) -> None:
        with self.assertRaisesRegex(ValueError, "malformed"):
            MarketSession.from_alpaca({"date": "bad", "open": "09:30", "close": "16:00"})
        with self.assertRaisesRegex(ValueError, "after"):
            MarketSession.from_alpaca(
                {"date": "2026-01-05", "open": "16:00", "close": "09:30"}
            )


if __name__ == "__main__":
    unittest.main()
