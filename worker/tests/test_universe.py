from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.universe import (
    UniverseMember,
    import_universe_snapshot_if_changed,
    import_universe_snapshot,
    read_members_csv,
    read_members_csv_text,
    read_members_history_csv,
    load_universe_timeline,
)


class UniverseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)

    def tearDown(self) -> None:
        self.connection.close()

    def test_import_is_order_independent_and_idempotent(self) -> None:
        members = [
            UniverseMember("MSFT", "Microsoft", "NASDAQ"),
            UniverseMember("aapl", "Apple", "nasdaq"),
        ]
        first = import_universe_snapshot(
            self.connection,
            members,
            universe="sp500",
            effective_at="2026-08-20T20:00:00Z",
            source="fixture",
        )
        second = import_universe_snapshot(
            self.connection,
            reversed(members),
            universe="sp500",
            effective_at="2026-08-20T20:00:00Z",
            source="fixture",
        )

        self.assertFalse(first.already_existed)
        self.assertTrue(second.already_existed)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(first.member_count, 2)
        stored = self.connection.execute(
            """
            SELECT i.symbol FROM universe_memberships um
            JOIN instruments i ON i.id = um.instrument_id
            WHERE um.snapshot_id = ? ORDER BY i.symbol
            """,
            (first.snapshot_id,),
        ).fetchall()
        self.assertEqual([row["symbol"] for row in stored], ["AAPL", "MSFT"])

    def test_changed_membership_creates_a_new_snapshot(self) -> None:
        first = import_universe_snapshot(
            self.connection,
            [UniverseMember("AAPL")],
            universe="sp500",
            effective_at="2026-08-20",
            source="fixture",
        )
        second = import_universe_snapshot(
            self.connection,
            [UniverseMember("AAPL"), UniverseMember("MSFT")],
            universe="sp500",
            effective_at="2026-08-20",
            source="fixture",
        )
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)

    def test_conflicting_duplicates_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            import_universe_snapshot(
                self.connection,
                [UniverseMember("AAPL", "Apple"), UniverseMember("AAPL", "Other")],
                universe="sp500",
                effective_at="2026-08-20",
                source="fixture",
            )

    def test_reads_common_csv_column_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "members.csv"
            path.write_text(
                "Ticker,Security,Exchange,CIK\nAAPL,Apple Inc.,NASDAQ,0000320193\n",
                encoding="utf-8",
            )
            members = read_members_csv(path)
        self.assertEqual(
            members,
            [UniverseMember("AAPL", "Apple Inc.", "NASDAQ", "320193")],
        )

    def test_reads_csv_text_and_change_aware_import_avoids_daily_duplicates(self) -> None:
        members = read_members_csv_text("Symbol,CIK\nAAPL,0000320193\n")
        first = import_universe_snapshot_if_changed(
            self.connection,
            members,
            universe="sp500",
            effective_at="2026-08-20T10:00:00Z",
            source="fixture",
        )
        unchanged = import_universe_snapshot_if_changed(
            self.connection,
            members,
            universe="sp500",
            effective_at="2026-08-20T11:00:00Z",
            source="fixture",
        )
        self.assertEqual(unchanged.snapshot_id, first.snapshot_id)
        self.assertTrue(unchanged.already_existed)
        with self.assertRaisesRegex(ValueError, "same effective date"):
            import_universe_snapshot_if_changed(
                self.connection,
                [*members, UniverseMember("MSFT", cik="789019")],
                universe="sp500",
                effective_at="2026-08-20T12:00:00Z",
                source="fixture",
            )

    def test_rejects_non_numeric_cik(self) -> None:
        with self.assertRaisesRegex(ValueError, "CIK"):
            UniverseMember("AAPL", cik="not-a-cik")

    def test_reads_long_form_history_and_resolves_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.csv"
            path.write_text(
                "date,ticker,security\n"
                "2020-01-01,AAPL,Apple\n"
                "2020-01-01,OLD,Old Corp\n"
                "2020-06-01,AAPL,Apple\n"
                "2020-06-01,MSFT,Microsoft\n",
                encoding="utf-8",
            )
            inputs = read_members_history_csv(path)
        self.assertEqual([value.effective_at for value in inputs], ["2020-01-01", "2020-06-01"])
        imported = [
            import_universe_snapshot(
                self.connection,
                value.members,
                universe="sp500",
                effective_at=value.effective_at,
                source="fixture-history",
            )
            for value in inputs
        ]

        timeline = load_universe_timeline(
            self.connection,
            anchor_snapshot_id=imported[-1].snapshot_id,
            start=date(2020, 3, 1),
            end=date(2020, 8, 1),
        )

        self.assertEqual([value.snapshot_id for value in timeline], [result.snapshot_id for result in imported])
        self.assertEqual(timeline[0].members, ("AAPL", "OLD"))
        self.assertEqual(timeline[1].members, ("AAPL", "MSFT"))

    def test_timeline_rejects_missing_prior_coverage_and_same_day_ambiguity(self) -> None:
        first = import_universe_snapshot(
            self.connection,
            [UniverseMember("AAPL")],
            universe="sp500",
            effective_at="2020-06-01T09:00:00Z",
            source="fixture",
        )
        with self.assertRaisesRegex(ValueError, "on or before start"):
            load_universe_timeline(
                self.connection,
                anchor_snapshot_id=first.snapshot_id,
                start=date(2020, 1, 1),
                end=date(2020, 12, 31),
            )
        import_universe_snapshot(
            self.connection,
            [UniverseMember("MSFT")],
            universe="sp500",
            effective_at="2020-06-01T20:00:00Z",
            source="fixture",
        )
        with self.assertRaisesRegex(ValueError, "multiple snapshots"):
            load_universe_timeline(
                self.connection,
                anchor_snapshot_id=first.snapshot_id,
                start=date(2020, 6, 1),
                end=date(2020, 12, 31),
            )


if __name__ == "__main__":
    unittest.main()
