from __future__ import annotations

import sqlite3
import unittest
from datetime import date, timedelta

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.ingestion import persist_company_facts, persist_news_articles
from stock_watch_worker.providers.alpaca import NewsArticle
from stock_watch_worker.scan_data import load_scan_inputs


class ScanDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self._seed()

    def tearDown(self) -> None:
        self.connection.close()

    def test_open_scan_excludes_current_daily_bar_and_future_sources(self) -> None:
        inputs = load_scan_inputs(
            self.connection,
            scan_run_id="scan-open",
            news_coverage_complete=True,
        )

        self.assertEqual(inputs.scan_type, "open")
        self.assertEqual(inputs.spy_bars[-1].session, "2026-08-19")
        candidate = inputs.candidates[0]
        self.assertEqual(candidate.bars[-1].session, "2026-08-19")
        self.assertEqual(len(candidate.news_sentiments), 1)
        self.assertGreater(candidate.news_sentiments[0], 0)
        self.assertEqual(candidate.source_refs["company_facts_document_id"], 1)
        self.assertEqual(candidate.vetoes, ())

    def test_close_scan_includes_completed_current_daily_bar(self) -> None:
        inputs = load_scan_inputs(
            self.connection,
            scan_run_id="scan-close",
            news_coverage_complete=False,
        )

        self.assertEqual(inputs.spy_bars[-1].session, "2026-08-20")
        self.assertEqual(inputs.candidates[0].bars[-1].session, "2026-08-20")
        self.assertFalse(inputs.candidates[0].news_coverage_complete)

    def test_missing_fractional_eligibility_becomes_explicit_veto(self) -> None:
        self.connection.execute(
            "UPDATE instruments SET fractionable = NULL WHERE symbol = 'AAPL'"
        )
        inputs = load_scan_inputs(
            self.connection,
            scan_run_id="scan-open",
            news_coverage_complete=True,
        )

        self.assertIn("instrument_not_fractionable", inputs.candidates[0].vetoes)

    def test_requires_spy_and_sufficient_history_setting(self) -> None:
        with self.assertRaisesRegex(ValueError, "200"):
            load_scan_inputs(
                self.connection,
                scan_run_id="scan-open",
                news_coverage_complete=True,
                history_sessions=100,
            )
        self.connection.execute("DELETE FROM market_bars WHERE instrument_id = 2")
        inputs = load_scan_inputs(
            self.connection,
            scan_run_id="scan-open",
            news_coverage_complete=True,
        )
        self.assertEqual(inputs.spy_bars, ())

    def _seed(self) -> None:
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'development', '{}', 'hash', CURRENT_TIMESTAMP, NULL)"
        )
        self.connection.executemany(
            """
            INSERT INTO instruments(id, symbol, active, fractionable)
            VALUES (?, ?, 1, 1)
            """,
            ((1, "AAPL"), (2, "SPY")),
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-08-20', 'fixture', 'snapshot')
            """
        )
        self.connection.execute(
            "INSERT INTO universe_memberships VALUES (1, 1)"
        )
        for scan_id, scan_type, scheduled in (
            ("scan-open", "open", "2026-08-20T13:45:00Z"),
            ("scan-close", "close", "2026-08-20T20:15:00Z"),
        ):
            self.connection.execute(
                """
                INSERT INTO scan_runs(
                    id, strategy_version_id, universe_snapshot_id,
                    scan_type, scheduled_for, data_cutoff, status
                ) VALUES (?, 'strategy-v0', 1, ?, ?, ?, 'queued')
                """,
                (scan_id, scan_type, scheduled, scheduled),
            )
        start = date(2026, 1, 1)
        for instrument_id, multiplier in ((1, 1.002), (2, 1.0005)):
            close = 100.0
            rows = []
            for offset in range((date(2026, 8, 20) - start).days + 1):
                session = start + timedelta(days=offset)
                close *= multiplier
                rows.append(
                    (
                        instrument_id,
                        session.isoformat(),
                        "1Day",
                        close * 0.999,
                        close * 1.002,
                        close * 0.998,
                        close,
                        2_000_000,
                        "all",
                        "alpaca",
                    )
                )
            self.connection.executemany(
                """
                INSERT INTO market_bars(
                    instrument_id, timestamp, timeframe, open, high, low,
                    close, volume, adjustment, provider
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        persist_company_facts(
            self.connection,
            symbol="AAPL",
            captured_at="2026-08-20T13:00:00Z",
            company_facts={"facts": {}},
        )
        persist_company_facts(
            self.connection,
            symbol="AAPL",
            captured_at="2026-08-20T15:00:00Z",
            company_facts={"facts": {}, "future": True},
        )
        persist_news_articles(
            self.connection,
            [
                NewsArticle(
                    id=1,
                    headline="Apple beats estimates",
                    created_at="2026-08-20T12:00:00Z",
                    updated_at=None,
                    source="fixture",
                    summary=None,
                    url=None,
                    symbols=("AAPL",),
                    content=None,
                    raw={"id": 1},
                ),
                NewsArticle(
                    id=2,
                    headline="Future upgrade",
                    created_at="2026-08-20T21:00:00Z",
                    updated_at=None,
                    source="fixture",
                    summary=None,
                    url=None,
                    symbols=("AAPL",),
                    content=None,
                    raw={"id": 2},
                ),
            ],
        )
        self.connection.commit()


if __name__ == "__main__":
    unittest.main()
