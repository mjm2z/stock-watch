from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from stock_watch_worker.backtest_runner import load_backtest_dataset
from stock_watch_worker.config import load_strategy
from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations, register_strategy
from stock_watch_worker.historical_dataset import (
    build_historical_backtest_dataset,
    write_historical_backtest_dataset,
)


STRATEGY_PATH = Path(__file__).resolve().parents[1] / "config" / "strategy-v0.json"


class HistoricalDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        register_strategy(self.connection, load_strategy(STRATEGY_PATH))
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
                id, universe, effective_at, source, content_sha256,
                survivorship_biased
            ) VALUES (1, 'sp500', '2026-01-01', 'fixture', 'universe-hash', 1)
            """
        )
        self.connection.execute("INSERT INTO universe_memberships VALUES (1, 1)")
        self.sessions = [date(2025, 1, 1) + timedelta(days=index) for index in range(320)]
        rows: list[tuple[object, ...]] = []
        for instrument_id, daily_gain in ((1, 0.002), (2, 0.001)):
            price = 100.0
            for session in self.sessions:
                price *= 1 + daily_gain
                rows.append(
                    (
                        instrument_id,
                        f"{session.isoformat()}T05:00:00Z",
                        price,
                        price * 1.02,
                        price * 0.99,
                        price * 1.01,
                        1_000_000,
                    )
                )
        self.connection.executemany(
            """
            INSERT INTO market_bars(
                instrument_id, timestamp, timeframe, open, high, low, close,
                volume, adjustment, provider
            ) VALUES (?, ?, '1Day', ?, ?, ?, ?, ?, 'all', 'alpaca')
            """,
            rows,
        )
        self.connection.commit()

    def tearDown(self) -> None:
        self.connection.close()

    def test_builds_loadable_point_in_time_scored_manifest(self) -> None:
        result = build_historical_backtest_dataset(
            self.connection,
            strategy_version_id="sp500-long-v0",
            universe_snapshot_id=1,
            start=self.sessions[199],
            end=self.sessions[205],
            signal_stride_sessions=2,
            history_sessions=200,
        )

        self.assertEqual(result.stats.sessions_evaluated, 4)
        self.assertEqual(result.stats.scored_symbol_sessions, 4)
        self.assertEqual(result.stats.signals, 16)
        self.assertEqual(result.stats.qualified_signals, 0)
        self.assertTrue(result.manifest["provenance"]["survivorship_biased"])
        self.assertEqual(result.manifest["signals"][0]["data_completeness"], 50)
        self.assertEqual(set(result.manifest["bars"]), {"AAPL", "SPY"})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "historical.json"
            bytes_written = write_historical_backtest_dataset(path, result)
            loaded = load_backtest_dataset(path)
            self.assertEqual(len(loaded.signals), 16)
            self.assertGreater(bytes_written, 0)
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                write_historical_backtest_dataset(path, result)

    def test_requires_future_benchmark_history_for_maximum_horizon(self) -> None:
        with self.assertRaisesRegex(ValueError, "future SPY"):
            build_historical_backtest_dataset(
                self.connection,
                strategy_version_id="sp500-long-v0",
                universe_snapshot_id=1,
                start=self.sessions[250],
                end=self.sessions[319],
                history_sessions=200,
            )

    def test_signal_cap_prevents_accidental_oversized_manifest(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum_signals"):
            build_historical_backtest_dataset(
                self.connection,
                strategy_version_id="sp500-long-v0",
                universe_snapshot_id=1,
                start=self.sessions[199],
                end=self.sessions[205],
                history_sessions=200,
                maximum_signals=2,
            )

    def test_point_in_time_builder_switches_membership_at_effective_snapshot(self) -> None:
        self.connection.execute(
            "INSERT INTO instruments(id, symbol, active, fractionable) VALUES (3, 'MSFT', 1, 1)"
        )
        self.connection.executemany(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256,
                survivorship_biased
            ) VALUES (?, 'sp500', ?, 'fixture-history', ?, 0)
            """,
            (
                (2, self.sessions[0].isoformat(), "history-hash-1"),
                (3, self.sessions[202].isoformat(), "history-hash-2"),
            ),
        )
        self.connection.execute("INSERT INTO universe_memberships VALUES (2, 1)")
        self.connection.execute("INSERT INTO universe_memberships VALUES (3, 3)")
        price = 100.0
        rows = []
        for session in self.sessions:
            price *= 1.003
            rows.append(
                (
                    3,
                    f"{session.isoformat()}T05:00:00Z",
                    price,
                    price * 1.02,
                    price * 0.99,
                    price * 1.01,
                    1_000_000,
                )
            )
        self.connection.executemany(
            """
            INSERT INTO market_bars(
                instrument_id, timestamp, timeframe, open, high, low, close,
                volume, adjustment, provider
            ) VALUES (?, ?, '1Day', ?, ?, ?, ?, ?, 'all', 'alpaca')
            """,
            rows,
        )
        self.connection.commit()

        result = build_historical_backtest_dataset(
            self.connection,
            strategy_version_id="sp500-long-v0",
            universe_snapshot_id=3,
            start=self.sessions[199],
            end=self.sessions[205],
            signal_stride_sessions=2,
            history_sessions=200,
            point_in_time_universe=True,
        )

        provenance = result.manifest["provenance"]
        self.assertEqual(provenance["universe_membership_mode"], "point_in_time")
        self.assertFalse(provenance["survivorship_biased"])
        self.assertEqual([value["id"] for value in provenance["universe_snapshots"]], [2, 3])
        signals = result.manifest["signals"]
        by_session = {
            session: {(value["symbol"], value["universe_snapshot_id"]) for value in signals if value["signal_session"] == session}
            for session in {value["signal_session"] for value in signals}
        }
        self.assertEqual(by_session[self.sessions[199].isoformat()], {("AAPL", 2)})
        self.assertEqual(by_session[self.sessions[203].isoformat()], {("MSFT", 3)})
        self.assertEqual(set(result.manifest["bars"]), {"AAPL", "MSFT", "SPY"})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "point-in-time.json"
            write_historical_backtest_dataset(path, result)
            loaded = load_backtest_dataset(path)
        self.assertEqual(loaded.universe_membership_mode, "point_in_time")
        self.assertEqual(
            {value.universe_snapshot_id for value in loaded.signals}, {2, 3}
        )

    def test_uses_only_news_published_before_conservative_close_cutoff(self) -> None:
        coverage_start = self.sessions[196]
        coverage_end = self.sessions[205]
        self.connection.execute(
            """
            INSERT INTO data_ingestions(
                id, dataset, provider, started_at, completed_at, status,
                version, metadata_json
            ) VALUES (
                10, 'historical_news', 'alpaca', CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP, 'succeeded', 'fixture-news-v1', ?
            )
            """,
            (
                '{"end":"'
                + coverage_end.isoformat()
                + '","news_coverage_complete":true,"sentiment_model":"lexicon-v0",'
                + '"start":"'
                + coverage_start.isoformat()
                + '","symbol_list":["AAPL"]}',
            ),
        )
        session = self.sessions[199].isoformat()
        self.connection.executemany(
            """
            INSERT INTO news_articles(
                id, provider, published_at, headline, content_hash, raw_json,
                ingestion_id
            ) VALUES (?, 'alpaca', ?, ?, ?, '{}', 10)
            """,
            (
                ("alpaca:1", f"{session}T17:00:00Z", "AAPL beats estimates", "hash-1"),
                ("alpaca:2", f"{session}T20:00:00Z", "AAPL warning", "hash-2"),
            ),
        )
        self.connection.executemany(
            """
            INSERT INTO news_instruments(
                news_id, instrument_id, sentiment, sentiment_model
            ) VALUES (?, 1, ?, 'lexicon-v0')
            """,
            (("alpaca:1", 1.0), ("alpaca:2", -1.0)),
        )
        self.connection.execute(
            """
            INSERT INTO data_ingestions(
                id, dataset, provider, started_at, completed_at, status,
                version, metadata_json
            ) VALUES (
                20, 'historical_calendar', 'alpaca-paper', CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP, 'succeeded', 'fixture-calendar-v1', ?
            )
            """,
            (
                '{"calendar_coverage_complete":true,"end":"'
                + coverage_end.isoformat()
                + '","start":"'
                + self.sessions[199].isoformat()
                + '"}',
            ),
        )
        self.connection.executemany(
            """
            INSERT INTO market_sessions(
                trading_date, provider, opens_at, closes_at, ingestion_id
            ) VALUES (?, 'alpaca-paper', ?, ?, 20)
            """,
            (
                (
                    value.isoformat(),
                    f"{value.isoformat()}T13:30:00Z",
                    f"{value.isoformat()}T17:00:00Z",
                )
                for value in (self.sessions[199], self.sessions[201], self.sessions[203], self.sessions[205])
            ),
        )
        self.connection.commit()

        with self.assertRaisesRegex(ValueError, "requires a historical calendar"):
            build_historical_backtest_dataset(
                self.connection,
                strategy_version_id="sp500-long-v0",
                universe_snapshot_id=1,
                start=self.sessions[199],
                end=self.sessions[205],
                signal_stride_sessions=2,
                history_sessions=200,
                historical_news_ingestion_id=10,
            )

        result = build_historical_backtest_dataset(
            self.connection,
            strategy_version_id="sp500-long-v0",
            universe_snapshot_id=1,
            start=self.sessions[199],
            end=self.sessions[205],
            signal_stride_sessions=2,
            history_sessions=200,
            historical_news_ingestion_id=10,
            historical_calendar_ingestion_id=20,
            news_lookback_days=3,
        )

        self.assertTrue(result.manifest["provenance"]["news_coverage_complete"])
        self.assertEqual(result.manifest["provenance"]["news_ingestion"]["id"], 10)
        self.assertEqual(result.manifest["provenance"]["calendar_ingestion"]["id"], 20)
        self.assertEqual(
            result.manifest["provenance"]["news_cutoff_policy"],
            "provider exchange-session close",
        )
        self.assertEqual(result.manifest["signals"][0]["data_completeness"], 65)
        self.assertGreater(
            result.manifest["signals"][0]["opportunity_score"],
            result.manifest["signals"][4]["opportunity_score"],
        )
        self.assertEqual(result.stats.news_observations, 3)

        self.connection.execute(
            "UPDATE data_ingestions SET metadata_json = json_set(metadata_json, '$.start', ?) WHERE id = 10",
            (self.sessions[199].isoformat(),),
        )
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "requested dates"):
            build_historical_backtest_dataset(
                self.connection,
                strategy_version_id="sp500-long-v0",
                universe_snapshot_id=1,
                start=self.sessions[199],
                end=self.sessions[205],
                signal_stride_sessions=2,
                history_sessions=200,
                historical_news_ingestion_id=10,
                historical_calendar_ingestion_id=20,
                news_lookback_days=3,
            )


if __name__ == "__main__":
    unittest.main()
