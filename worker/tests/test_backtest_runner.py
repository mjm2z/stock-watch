from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from stock_watch_worker.backtest import BacktestResult
from stock_watch_worker.backtest_runner import (
    _point_selection_objective,
    _selection_objective,
    load_backtest_dataset,
    run_backtest,
)
from stock_watch_worker.config import load_strategy
from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations, register_strategy
from stock_watch_worker.outcomes import calculate_outcome, summarize_outcomes


STRATEGY_PATH = Path(__file__).resolve().parents[1] / "config" / "strategy-v0.json"
NOW = datetime(2026, 8, 20, 21, 0, tzinfo=timezone.utc)


class BacktestRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        register_strategy(self.connection, load_strategy(STRATEGY_PATH))
        self.connection.execute(
            """
            INSERT INTO instruments(id, symbol, active, fractionable)
            VALUES (1, 'AAPL', 1, 1)
            """
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
        self.connection.commit()

    def tearDown(self) -> None:
        self.connection.close()

    def test_runs_persists_and_idempotently_reuses_walk_forward_backtest(self) -> None:
        dataset = self._load(self._manifest())

        first = run_backtest(
            self.connection,
            dataset=dataset,
            strategy_version_id="sp500-long-v0",
            universe_snapshot_id=1,
            round_trip_cost_bps=10,
            now=NOW,
        )
        second = run_backtest(
            self.connection,
            dataset=dataset,
            strategy_version_id="sp500-long-v0",
            universe_snapshot_id=1,
            round_trip_cost_bps=10,
            now=NOW,
        )

        self.assertTrue(first.inserted)
        self.assertFalse(second.inserted)
        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual((first.trades, first.rejections, first.splits), (1, 2, 3))
        run = self.connection.execute("SELECT * FROM backtest_runs").fetchone()
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["dataset_sha256"], dataset.content_sha256)
        self.assertEqual(run["survivorship_biased"], 1)
        self.assertEqual(
            json.loads(run["config_json"])["portfolio_analytics_version"],
            "unlimited-funded-cohorts-v1",
        )
        metrics = json.loads(run["metrics_json"])
        self.assertEqual(metrics["trades"], 1)
        self.assertEqual(metrics["underpowered_validation_splits"], 3)
        self.assertEqual(
            metrics["validation_selection_objective"],
            "equal_weight_wilson_95_lower_bounds_for_positive_and_beat_spy",
        )
        self.assertEqual(metrics["selected_thresholds"], {"0": 75, "1": 75, "2": 75})
        reliability = metrics["out_of_sample_reliability"]
        self.assertEqual(reliability["basis"], "untouched_walk_forward_test_trades")
        self.assertFalse(reliability["probability_forecasts_available"])
        self.assertEqual(reliability["overall"]["status"], "underpowered")
        self.assertEqual(reliability["overall"]["observations"], 1)
        self.assertEqual(reliability["overall"]["positive_return"]["successes"], 1)
        self.assertIn("5", reliability["by_horizon_and_score_bucket"])
        self.assertEqual(metrics["rejections_by_reason"]["duplicate_open_lot"], 1)
        self.assertEqual(metrics["rejections_by_reason"]["score_below_threshold"], 1)
        self.assertIn("summary", metrics)
        portfolio = metrics["portfolio"]
        self.assertEqual(
            portfolio["capital_model"],
            "unlimited_external_funding_fixed_trade_notional",
        )
        self.assertEqual(portfolio["stock"]["contributed_usd"], 10)
        self.assertEqual(portfolio["exposure"]["peak_concurrent_lots"], 1)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM backtest_splits").fetchone()[0],
            3,
        )
        validation = json.loads(
            self.connection.execute(
                """
                SELECT validation_metrics_json FROM backtest_splits
                WHERE backtest_run_id = ? AND split_index = 0
                """,
                (first.run_id,),
            ).fetchone()[0]
        )
        self.assertTrue(validation["underpowered"])
        self.assertEqual(validation["minimum_required_trades"], 20)
        self.assertEqual(validation["selected_threshold"], 75)
        trade = self.connection.execute("SELECT * FROM backtest_trades").fetchone()
        self.assertEqual(trade["signal_session"], "2026-01-13")
        self.assertEqual(trade["notional_usd"], 10)

    def test_cost_assumption_creates_a_distinct_reproducible_run(self) -> None:
        dataset = self._load(self._manifest())

        first = run_backtest(
            self.connection,
            dataset=dataset,
            strategy_version_id="sp500-long-v0",
            universe_snapshot_id=1,
            round_trip_cost_bps=10,
            now=NOW,
        )
        second = run_backtest(
            self.connection,
            dataset=dataset,
            strategy_version_id="sp500-long-v0",
            universe_snapshot_id=1,
            round_trip_cost_bps=25,
            now=NOW,
        )

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0],
            2,
        )

    def test_conservative_validation_objective_penalizes_a_lucky_small_cohort(self) -> None:
        winner = calculate_outcome(
            entry_price=100,
            terminal_price=110,
            observed_highs=[110],
            observed_lows=[100],
            spy_entry_price=100,
            spy_terminal_price=101,
            round_trip_cost_bps=0,
        )
        loser = calculate_outcome(
            entry_price=100,
            terminal_price=90,
            observed_highs=[100],
            observed_lows=[90],
            spy_entry_price=100,
            spy_terminal_price=101,
            round_trip_cost_bps=0,
        )

        def result(outcomes):
            values = tuple(outcomes)
            return BacktestResult(
                trades=tuple(SimpleNamespace(outcome=value) for value in values),
                rejected=(),
                summary=summarize_outcomes(values),
            )

        lucky_small = result([winner])
        supported = result([winner] * 8 + [loser] * 2)

        self.assertGreater(
            _point_selection_objective(lucky_small),
            _point_selection_objective(supported),
        )
        self.assertLess(
            _selection_objective(lucky_small),
            _selection_objective(supported),
        )

    def test_selects_threshold_on_validation_then_freezes_it_for_test(self) -> None:
        self.connection.execute(
            """
            INSERT INTO instruments(id, symbol, active, fractionable)
            VALUES (2, 'MSFT', 1, 1)
            """
        )
        self.connection.execute("INSERT INTO universe_memberships VALUES (1, 2)")
        self.connection.commit()
        dataset = self._load(self._calibration_manifest())

        result = run_backtest(
            self.connection,
            dataset=dataset,
            strategy_version_id="sp500-long-v0",
            universe_snapshot_id=1,
            minimum_validation_trades=1,
            now=NOW,
        )

        first_split = self.connection.execute(
            """
            SELECT selected_threshold, validation_metrics_json
            FROM backtest_splits
            WHERE backtest_run_id = ? AND split_index = 0
            """,
            (result.run_id,),
        ).fetchone()
        validation = json.loads(first_split["validation_metrics_json"])
        self.assertEqual(first_split["selected_threshold"], 88)
        self.assertFalse(validation["underpowered"])
        self.assertAlmostEqual(
            validation["thresholds"]["88"]["objective"], 0.2065493
        )
        self.assertEqual(validation["thresholds"]["88"]["point_objective"], 1)
        traded_symbols = [
            row[0]
            for row in self.connection.execute(
                """
                SELECT instruments.symbol FROM backtest_trades
                JOIN instruments ON instruments.id = backtest_trades.instrument_id
                WHERE backtest_run_id = ?
                """,
                (result.run_id,),
            )
        ]
        self.assertEqual(traded_symbols, ["MSFT"])
        rejection = self.connection.execute(
            """
            SELECT symbol, reason FROM backtest_rejections
            WHERE backtest_run_id = ?
            """,
            (result.run_id,),
        ).fetchone()
        self.assertEqual(tuple(rejection), ("AAPL", "score_below_threshold"))

    def test_manifest_rejects_open_scans_and_overlapping_test_windows(self) -> None:
        manifest = self._manifest()
        manifest["scan_type"] = "open"
        with self.assertRaisesRegex(ValueError, "close-generated"):
            self._load(manifest)

        manifest = self._manifest()
        manifest["walk_forward"]["step_sessions"] = 2
        with self.assertRaisesRegex(ValueError, "overlap"):
            self._load(manifest)

    def test_verifies_point_in_time_snapshot_provenance_and_latest_membership(self) -> None:
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256,
                survivorship_biased
            ) VALUES (2, 'sp500', '2026-01-05', 'fixture', 'universe-hash-2', 0)
            """
        )
        self.connection.execute("INSERT INTO universe_memberships VALUES (2, 1)")
        self.connection.commit()
        manifest = self._manifest()
        manifest["provenance"] = {
            "universe_membership_mode": "point_in_time",
            "universe_snapshots": [
                {
                    "id": 1,
                    "effective_at": "2026-01-01",
                    "content_sha256": "universe-hash",
                    "survivorship_biased": True,
                },
                {
                    "id": 2,
                    "effective_at": "2026-01-05",
                    "content_sha256": "universe-hash-2",
                    "survivorship_biased": False,
                },
            ],
        }
        manifest["signals"].append(
            {
                "symbol": "AAPL",
                "signal_session": "2026-01-03",
                "horizon_trading_days": 5,
                "opportunity_score": 85,
                "data_completeness": 100,
                "risk_level": "low",
                "vetoes": [],
            }
        )
        for signal in manifest["signals"]:
            signal["universe_snapshot_id"] = (
                1 if signal["signal_session"] < "2026-01-05" else 2
            )
        dataset = self._load(manifest)

        result = run_backtest(
            self.connection,
            dataset=dataset,
            strategy_version_id="sp500-long-v0",
            universe_snapshot_id=2,
            now=NOW,
        )

        self.assertEqual(result.metrics["universe_membership_mode"], "point_in_time")
        self.assertEqual(result.metrics["universe_snapshots"], [1, 2])
        stored = self.connection.execute(
            "SELECT survivorship_biased FROM backtest_runs WHERE id = ?",
            (result.run_id,),
        ).fetchone()
        self.assertEqual(stored["survivorship_biased"], 1)

        manifest["signals"][0]["universe_snapshot_id"] = 1
        invalid = self._load(manifest)
        with self.assertRaisesRegex(ValueError, "latest effective"):
            run_backtest(
                self.connection,
                dataset=invalid,
                strategy_version_id="sp500-long-v0",
                universe_snapshot_id=2,
                now=NOW,
            )

    def _load(self, manifest: dict[str, object]):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            return load_backtest_dataset(path)

    def _manifest(self) -> dict[str, object]:
        sessions = [date(2026, 1, 1) + timedelta(days=index) for index in range(24)]

        def bars(daily_gain: float) -> list[dict[str, object]]:
            result: list[dict[str, object]] = []
            price = 100.0
            for session in sessions:
                price *= 1 + daily_gain
                result.append(
                    {
                        "session": session.isoformat(),
                        "open": price,
                        "high": price * 1.02,
                        "low": price * 0.99,
                        "close": price * 1.01,
                        "volume": 1_000_000,
                    }
                )
            return result

        def signal(session: str, score: float = 85) -> dict[str, object]:
            return {
                "symbol": "AAPL",
                "signal_session": session,
                "horizon_trading_days": 5,
                "opportunity_score": score,
                "data_completeness": 100,
                "risk_level": "low",
                "vetoes": [],
            }

        return {
            "schema_version": 1,
            "dataset_version": "fixture-v1",
            "feature_set_version": "features-v0",
            "scan_type": "close",
            "walk_forward": {
                "train_sessions": 8,
                "validation_sessions": 4,
                "test_sessions": 4,
                "step_sessions": 4,
                "expanding": True,
            },
            "bars": {"AAPL": bars(0.005), "SPY": bars(0.001)},
            "signals": [
                signal("2026-01-09"),
                signal("2026-01-13"),
                signal("2026-01-17"),
                signal("2026-01-21", 70),
            ],
        }

    def _calibration_manifest(self) -> dict[str, object]:
        sessions = [date(2026, 1, 1) + timedelta(days=index) for index in range(24)]

        def bars(daily_gain: float) -> list[dict[str, object]]:
            result: list[dict[str, object]] = []
            price = 100.0
            for session in sessions:
                price *= 1 + daily_gain
                result.append(
                    {
                        "session": session.isoformat(),
                        "open": price,
                        "high": price * 1.02,
                        "low": price * 0.98,
                        "close": price,
                        "volume": 1_000_000,
                    }
                )
            return result

        def signal(symbol: str, session: str, score: float) -> dict[str, object]:
            return {
                "symbol": symbol,
                "signal_session": session,
                "horizon_trading_days": 5,
                "opportunity_score": score,
                "data_completeness": 100,
                "risk_level": "low",
                "vetoes": [],
            }

        return {
            "schema_version": 1,
            "dataset_version": "calibration-v1",
            "feature_set_version": "features-v0",
            "scan_type": "close",
            "walk_forward": {
                "train_sessions": 8,
                "validation_sessions": 4,
                "test_sessions": 4,
                "step_sessions": 4,
                "expanding": True,
            },
            "bars": {
                "AAPL": bars(-0.01),
                "MSFT": bars(0.01),
                "SPY": bars(0.001),
            },
            "signals": [
                signal("AAPL", "2026-01-09", 85),
                signal("MSFT", "2026-01-09", 95),
                signal("AAPL", "2026-01-13", 85),
                signal("MSFT", "2026-01-13", 95),
            ],
        }


if __name__ == "__main__":
    unittest.main()
