from __future__ import annotations

import sqlite3
import unittest
from typing import Sequence

from stock_watch_worker.collectors import AlpacaScanCollector
from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.providers.alpaca import AlpacaAsset, MarketBar, NewsArticle


class FakeMarketData:
    def __init__(self) -> None:
        self.bar_calls: list[tuple[str, ...]] = []
        self.news_calls = 0

    def get_historical_bars(
        self,
        symbols: Sequence[str],
        **kwargs: object,
    ) -> list[MarketBar]:
        self.bar_calls.append(tuple(symbols))
        return [
            MarketBar(
                symbol=symbol,
                timestamp="2026-08-19",
                open=100,
                high=102,
                low=99,
                close=101,
                volume=1_000_000,
                trade_count=100,
                vwap=100.5,
            )
            for symbol in symbols
        ]

    def get_news(self, **kwargs: object) -> list[NewsArticle]:
        self.news_calls += 1
        return [
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
            )
        ]


class FakePaperTrading:
    def __init__(self) -> None:
        self.calls = 0

    def get_assets(self) -> list[AlpacaAsset]:
        self.calls += 1
        return [
            AlpacaAsset(
                id="asset-aapl",
                symbol="AAPL",
                name="Apple Inc.",
                exchange="NASDAQ",
                status="active",
                tradable=True,
                fractionable=True,
            )
        ]


class AlpacaCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self._seed()

    def tearDown(self) -> None:
        self.connection.close()

    def test_collects_once_and_reuses_succeeded_ingestion_on_retry(self) -> None:
        market = FakeMarketData()
        paper = FakePaperTrading()
        collector = AlpacaScanCollector(
            market, paper, symbol_chunk_size=1, history_calendar_days=300
        )

        first = collector.collect_scan(self.connection, scan_run_id="scan-1")
        second = collector.collect_scan(self.connection, scan_run_id="scan-1")

        self.assertTrue(first.news_coverage_complete)
        self.assertTrue(second.news_coverage_complete)
        self.assertEqual(paper.calls, 1)
        self.assertEqual(market.news_calls, 1)
        self.assertEqual(market.bar_calls, [("AAPL",), ("SPY",)])
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0], 2
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM news_articles").fetchone()[0], 1
        )
        instrument = self.connection.execute(
            "SELECT fractionable FROM instruments WHERE symbol = 'AAPL'"
        ).fetchone()
        self.assertEqual(instrument["fractionable"], 1)
        ingestion = self.connection.execute(
            "SELECT status, metadata_json FROM data_ingestions"
        ).fetchone()
        self.assertEqual(ingestion["status"], "succeeded")
        self.assertIn('"news_coverage_complete":true', ingestion["metadata_json"])

    def _seed(self) -> None:
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'development', '{}', 'hash', CURRENT_TIMESTAMP, NULL)"
        )
        self.connection.execute(
            "INSERT INTO instruments(id, symbol) VALUES (1, 'AAPL')"
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-08-20', 'fixture', 'snapshot')
            """
        )
        self.connection.execute("INSERT INTO universe_memberships VALUES (1, 1)")
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-1', 'strategy-v0', 1, 'open',
                '2026-08-20T13:45:00Z', '2026-08-20T13:45:00Z', 'queued'
            )
            """
        )
        self.connection.commit()


if __name__ == "__main__":
    unittest.main()
