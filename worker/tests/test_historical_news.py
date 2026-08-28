from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import date
from typing import Sequence

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.historical_news import backfill_historical_news
from stock_watch_worker.providers.alpaca import NewsArticle


class FakeNewsProvider:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []
        self.fail_on_call = fail_on_call

    def get_news(
        self,
        *,
        start: str,
        end: str,
        symbols: Sequence[str] = (),
        include_content: bool = False,
    ) -> list[NewsArticle]:
        self.calls.append((start, end, tuple(symbols)))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("fixture news failure")
        article_id = len(self.calls)
        symbol = symbols[0]
        return [
            NewsArticle(
                id=article_id,
                headline=f"{symbol} beats estimates",
                created_at=start,
                updated_at=None,
                source="fixture",
                summary=None,
                url=None,
                symbols=(symbol,),
                content=None,
                raw={"id": article_id, "symbols": [symbol]},
            )
        ]


class HistoricalNewsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.connection.executemany(
            "INSERT INTO instruments(id, symbol) VALUES (?, ?)",
            ((1, "AAPL"), (2, "MSFT")),
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-01-01', 'fixture', 'snapshot-hash')
            """
        )
        self.connection.executemany(
            "INSERT INTO universe_memberships VALUES (1, ?)", ((1,), (2,))
        )
        self.connection.commit()

    def tearDown(self) -> None:
        self.connection.close()

    def test_backfills_bounded_windows_and_reuses_succeeded_ingestion(self) -> None:
        provider = FakeNewsProvider()
        first = backfill_historical_news(
            self.connection,
            provider=provider,
            universe_snapshot_id=1,
            start=date(2026, 1, 1),
            end=date(2026, 1, 3),
            symbol_chunk_size=1,
            window_days=2,
        )
        second = backfill_historical_news(
            self.connection,
            provider=provider,
            universe_snapshot_id=1,
            start=date(2026, 1, 1),
            end=date(2026, 1, 3),
            symbol_chunk_size=1,
            window_days=2,
        )

        self.assertEqual(first.logical_requests, 4)
        self.assertEqual(first.articles_inserted, 4)
        self.assertTrue(second.already_succeeded)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(provider.calls[0][0], "2026-01-01T00:00:00Z")
        self.assertEqual(provider.calls[-1][1], "2026-01-03T23:59:59.999999Z")
        metadata = json.loads(
            self.connection.execute("SELECT metadata_json FROM data_ingestions").fetchone()[0]
        )
        self.assertTrue(metadata["news_coverage_complete"])
        self.assertEqual(metadata["symbol_list"], ["AAPL", "MSFT"])

    def test_failed_backfill_is_restartable(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            backfill_historical_news(
                self.connection,
                provider=FakeNewsProvider(fail_on_call=2),
                universe_snapshot_id=1,
                start=date(2026, 1, 1),
                end=date(2026, 1, 1),
                symbol_chunk_size=1,
            )
        failed = self.connection.execute("SELECT * FROM data_ingestions").fetchone()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["request_count"], 2)

        result = backfill_historical_news(
            self.connection,
            provider=FakeNewsProvider(),
            universe_snapshot_id=1,
            start=date(2026, 1, 1),
            end=date(2026, 1, 1),
            symbol_chunk_size=1,
        )
        self.assertFalse(result.already_succeeded)
        self.assertGreaterEqual(result.articles_unchanged, 1)


if __name__ == "__main__":
    unittest.main()
