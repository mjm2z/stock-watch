from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import date
from typing import Sequence

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.historical_backfill import backfill_historical_bars
from stock_watch_worker.providers.alpaca import MarketBar


class FakeBarsProvider:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[tuple[str, ...], str, str]] = []
        self.fail_on_call = fail_on_call

    def get_historical_bars(
        self,
        symbols: Sequence[str],
        *,
        timeframe: str,
        start: str,
        end: str,
        adjustment: str = "all",
        feed: str = "iex",
    ) -> list[MarketBar]:
        self.calls.append((tuple(symbols), start, end))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("fixture provider failure")
        return [
            MarketBar(
                symbol=symbol,
                timestamp="2026-01-02T05:00:00Z",
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


class HistoricalBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.connection.executemany(
            """
            INSERT INTO instruments(id, symbol, active, fractionable)
            VALUES (?, ?, 1, 1)
            """,
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

    def test_backfills_universe_and_spy_then_reuses_succeeded_ingestion(self) -> None:
        provider = FakeBarsProvider()

        first = backfill_historical_bars(
            self.connection,
            provider=provider,
            universe_snapshot_id=1,
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
            symbol_chunk_size=1,
        )
        second = backfill_historical_bars(
            self.connection,
            provider=provider,
            universe_snapshot_id=1,
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
            symbol_chunk_size=1,
        )

        self.assertEqual(first.symbols, 3)
        self.assertEqual(first.logical_requests, 3)
        self.assertEqual(first.bars_inserted, 3)
        self.assertFalse(first.already_succeeded)
        self.assertTrue(second.already_succeeded)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(provider.calls[0], (("AAPL",), "2026-01-01", "2026-01-31"))
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0],
            3,
        )

    def test_failed_ingestion_is_restartable_without_duplicate_bars(self) -> None:
        failing = FakeBarsProvider(fail_on_call=2)

        with self.assertRaisesRegex(RuntimeError, "fixture"):
            backfill_historical_bars(
                self.connection,
                provider=failing,
                universe_snapshot_id=1,
                start=date(2026, 1, 1),
                end=date(2026, 1, 31),
                symbol_chunk_size=1,
            )
        failed = self.connection.execute("SELECT * FROM data_ingestions").fetchone()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["request_count"], 2)
        self.assertEqual(failed["row_count"], 1)

        result = backfill_historical_bars(
            self.connection,
            provider=FakeBarsProvider(),
            universe_snapshot_id=1,
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
            symbol_chunk_size=1,
        )

        self.assertEqual(result.bars_inserted, 2)
        self.assertEqual(result.bars_unchanged, 1)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM market_bars").fetchone()[0],
            3,
        )

    def test_rejects_invalid_range_before_provider_call(self) -> None:
        provider = FakeBarsProvider()
        with self.assertRaisesRegex(ValueError, "start"):
            backfill_historical_bars(
                self.connection,
                provider=provider,
                universe_snapshot_id=1,
                start=date(2026, 2, 1),
                end=date(2026, 1, 1),
            )
        self.assertEqual(provider.calls, [])

    def test_point_in_time_backfill_uses_union_of_constituent_snapshots(self) -> None:
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (2, 'sp500', '2026-01-15', 'fixture', 'snapshot-hash-2')
            """
        )
        self.connection.execute("INSERT INTO universe_memberships VALUES (2, 1)")
        self.connection.commit()
        provider = FakeBarsProvider()

        result = backfill_historical_bars(
            self.connection,
            provider=provider,
            universe_snapshot_id=2,
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
            symbol_chunk_size=10,
            point_in_time_universe=True,
        )

        self.assertEqual(result.symbols, 3)
        self.assertEqual(provider.calls[0][0], ("AAPL", "MSFT", "SPY"))
        ingestion = self.connection.execute(
            "SELECT metadata_json FROM data_ingestions WHERE id = ?",
            (result.ingestion_id,),
        ).fetchone()
        metadata = json.loads(ingestion["metadata_json"])
        self.assertEqual(metadata["universe_membership_mode"], "point_in_time")
        self.assertEqual(metadata["universe_snapshot_ids"], [1, 2])


if __name__ == "__main__":
    unittest.main()
