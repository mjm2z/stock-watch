from __future__ import annotations

import sqlite3
import unittest

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.ingestion import (
    DataConflictError,
    persist_company_facts,
    persist_market_bars,
    persist_news_articles,
    refresh_asset_metadata,
)
from stock_watch_worker.providers.alpaca import AlpacaAsset, MarketBar, NewsArticle


class IngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.connection.executemany(
            "INSERT INTO instruments(symbol, name) VALUES (?, ?)",
            (("AAPL", "Apple"), ("SPY", "SPDR S&P 500 ETF")),
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'fixture', '2026-01-01', 'fixture', 'fixture')
            """
        )
        self.connection.execute(
            "INSERT INTO universe_memberships SELECT 1, id FROM instruments"
        )

    def tearDown(self) -> None:
        self.connection.close()

    def test_market_bars_are_idempotent_but_not_silently_mutable(self) -> None:
        bar = self._bar(close=104)
        first = persist_market_bars(
            self.connection,
            [bar],
            timeframe="1Day",
            adjustment="all",
            provider="alpaca",
        )
        second = persist_market_bars(
            self.connection,
            [bar],
            timeframe="1Day",
            adjustment="all",
            provider="alpaca",
        )

        self.assertEqual(first.inserted, 1)
        self.assertEqual(second.unchanged, 1)
        with self.assertRaisesRegex(DataConflictError, "immutable bar changed"):
            persist_market_bars(
                self.connection,
                [self._bar(close=103)],
                timeframe="1Day",
                adjustment="all",
                provider="alpaca",
            )

    def test_rejects_unknown_instrument_and_invalid_ohlc(self) -> None:
        unknown = MarketBar("MSFT", "2026-01-02T05:00:00Z", 100, 105, 99, 104, 1000, None, None)
        with self.assertRaisesRegex(ValueError, "unknown instruments"):
            persist_market_bars(
                self.connection,
                [unknown],
                timeframe="1Day",
                adjustment="all",
                provider="alpaca",
            )

        invalid = MarketBar("AAPL", "2026-01-02T05:00:00Z", 100, 101, 99, 104, 1000, None, None)
        with self.assertRaisesRegex(ValueError, "high is inconsistent"):
            persist_market_bars(
                self.connection,
                [invalid],
                timeframe="1Day",
                adjustment="all",
                provider="alpaca",
            )

    def test_news_links_known_symbols_and_reports_unknown_ones(self) -> None:
        article = NewsArticle(
            id=7,
            headline="Apple update",
            created_at="2026-01-02T12:00:00Z",
            updated_at=None,
            source="Fixture",
            summary=None,
            url="https://example.test/7",
            symbols=("AAPL", "UNKNOWN"),
            content=None,
            raw={"id": 7, "headline": "Apple update"},
        )
        first = persist_news_articles(self.connection, [article])
        second = persist_news_articles(self.connection, [article])

        self.assertEqual(first.inserted, 1)
        self.assertEqual(first.skipped_unknown_symbols, ("UNKNOWN",))
        self.assertEqual(second.unchanged, 1)
        links = self.connection.execute("SELECT COUNT(*) AS count FROM news_instruments").fetchone()
        self.assertEqual(links["count"], 1)
        link = self.connection.execute(
            "SELECT sentiment, sentiment_model FROM news_instruments"
        ).fetchone()
        self.assertEqual(link["sentiment"], 0)
        self.assertEqual(link["sentiment_model"], "lexicon-v0")

    def test_changed_news_payload_is_a_conflict(self) -> None:
        original = self._article({"id": 9, "headline": "First"})
        changed = self._article({"id": 9, "headline": "Changed"})
        persist_news_articles(self.connection, [original])
        with self.assertRaisesRegex(DataConflictError, "immutable news article changed"):
            persist_news_articles(self.connection, [changed])

    def test_refreshes_fractional_asset_metadata_for_snapshot_members(self) -> None:
        asset = AlpacaAsset(
            id="asset-aapl",
            symbol="AAPL",
            name="Apple Inc.",
            exchange="NASDAQ",
            status="active",
            tradable=True,
            fractionable=True,
        )

        first = refresh_asset_metadata(
            self.connection, [asset], universe_snapshot_id=1
        )
        second = refresh_asset_metadata(
            self.connection, [asset], universe_snapshot_id=1
        )

        self.assertEqual(first.updated, 1)
        self.assertEqual(first.missing_symbols, ("SPY",))
        self.assertEqual(second.unchanged, 1)
        instrument = self.connection.execute(
            "SELECT alpaca_asset_id, active, fractionable FROM instruments WHERE symbol = 'AAPL'"
        ).fetchone()
        self.assertEqual(tuple(instrument), ("asset-aapl", 1, 1))

    def test_company_facts_are_point_in_time_and_immutable(self) -> None:
        facts = {"cik": 320193, "facts": {"us-gaap": {}}}
        first = persist_company_facts(
            self.connection,
            symbol="AAPL",
            captured_at="2026-08-20T14:00:00Z",
            company_facts=facts,
        )
        second = persist_company_facts(
            self.connection,
            symbol="AAPL",
            captured_at="2026-08-20T14:00:00Z",
            company_facts=facts,
        )

        self.assertTrue(first.inserted)
        self.assertFalse(second.inserted)
        self.assertEqual(first.document_id, second.document_id)
        with self.assertRaisesRegex(DataConflictError, "CompanyFacts changed"):
            persist_company_facts(
                self.connection,
                symbol="AAPL",
                captured_at="2026-08-20T14:00:00Z",
                company_facts={"changed": True},
            )

    @staticmethod
    def _bar(close: float) -> MarketBar:
        return MarketBar(
            symbol="AAPL",
            timestamp="2026-01-02T05:00:00Z",
            open=100,
            high=105,
            low=99,
            close=close,
            volume=1000,
            trade_count=50,
            vwap=102,
        )

    @staticmethod
    def _article(raw: dict) -> NewsArticle:
        return NewsArticle(
            id=9,
            headline=str(raw["headline"]),
            created_at="2026-01-02T12:00:00Z",
            updated_at=None,
            source="Fixture",
            summary=None,
            url=None,
            symbols=("AAPL",),
            content=None,
            raw=raw,
        )


if __name__ == "__main__":
    unittest.main()
