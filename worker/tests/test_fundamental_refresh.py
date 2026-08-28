from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.fundamental_refresh import refresh_company_facts
from stock_watch_worker.http import ProviderError
from stock_watch_worker.ingestion import persist_company_facts


NOW = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)


class FakeSec:
    def __init__(self, unavailable_cik: str | None = None) -> None:
        self.calls: list[str] = []
        self.unavailable_cik = unavailable_cik

    def get_company_facts(self, cik: str) -> Mapping[str, Any]:
        self.calls.append(cik)
        if cik == self.unavailable_cik:
            raise ProviderError("sec", 404, "not found", retryable=False)
        return {"cik": int(cik), "facts": {}}


class FundamentalRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.connection.executemany(
            "INSERT INTO instruments(id, symbol, cik) VALUES (?, ?, ?)",
            ((1, "AAPL", "320193"), (2, "MSFT", "789019"), (3, "MISSING", None)),
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-08-20', 'fixture', 'snapshot')
            """
        )
        self.connection.execute(
            "INSERT INTO universe_memberships SELECT 1, id FROM instruments"
        )
        persist_company_facts(
            self.connection,
            symbol="AAPL",
            captured_at="2026-08-20T00:00:00Z",
            company_facts={"facts": {}},
        )
        self.connection.commit()

    def tearDown(self) -> None:
        self.connection.close()

    def test_skips_fresh_cache_and_reports_missing_or_unavailable_cik(self) -> None:
        sec = FakeSec(unavailable_cik="789019")

        result = refresh_company_facts(
            self.connection,
            sec=sec,
            universe_snapshot_id=1,
            now=NOW,
        )

        self.assertEqual(result.refreshed, 0)
        self.assertEqual(result.skipped_fresh, 1)
        self.assertEqual(result.missing_cik, ("MISSING",))
        self.assertEqual(result.unavailable, ("MSFT",))
        self.assertEqual(sec.calls, ["789019"])

    def test_refreshes_stale_company_facts(self) -> None:
        sec = FakeSec()
        progress: list[tuple[int, int, str]] = []
        result = refresh_company_facts(
            self.connection,
            sec=sec,
            universe_snapshot_id=1,
            now=NOW + timedelta(days=2),
            progress=lambda current, total, message: progress.append(
                (current, total, message)
            ),
        )

        self.assertEqual(result.refreshed, 2)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM company_fact_documents"
            ).fetchone()[0],
            3,
        )
        self.assertEqual(progress[0][:2], (0, 3))
        self.assertEqual(progress[-1][:2], (3, 3))
        self.assertIn("refreshed=2", progress[-1][2])


if __name__ == "__main__":
    unittest.main()
