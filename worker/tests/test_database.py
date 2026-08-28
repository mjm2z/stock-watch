from __future__ import annotations

import sqlite3
import unittest

from stock_watch_worker.database import (
    INSTALLED_MIGRATIONS_DIR,
    MIGRATIONS_DIR,
    SOURCE_MIGRATIONS_DIR,
    apply_migrations,
)


class DatabaseMigrationTests(unittest.TestCase):
    def test_source_and_installed_migration_locations_are_defined(self) -> None:
        self.assertEqual(MIGRATIONS_DIR, SOURCE_MIGRATIONS_DIR)
        self.assertEqual(
            INSTALLED_MIGRATIONS_DIR.parts[-3:],
            ("share", "stock-watch-worker", "migrations"),
        )

    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def tearDown(self) -> None:
        self.connection.close()

    def test_initial_migration_creates_core_tables(self) -> None:
        applied = apply_migrations(self.connection, MIGRATIONS_DIR)
        self.assertEqual(
            applied,
            [
                "001_initial",
                "002_backtests",
                "003_job_leases",
                "004_company_facts",
                "005_paper_exits",
                "006_portfolio_attribution",
                "007_broker_reconciliation",
                "008_market_sessions",
                "009_observability",
            ],
        )

        tables = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(
            {
                "strategy_versions",
                "scan_runs",
                "signals",
                "paper_orders",
                "paper_trade_lots",
                "paper_exit_orders",
                "paper_exit_fills",
                "signal_outcomes",
                "job_runs",
                "backtest_runs",
                "backtest_splits",
                "backtest_trades",
                "backtest_rejections",
                "company_fact_documents",
                "broker_account_snapshots",
                "broker_position_snapshots",
                "broker_account_activities",
                "broker_reconciliations",
                "market_sessions",
                "operation_runs",
                "operation_events",
            }.issubset(tables)
        )

    def test_backtest_split_boundaries_must_be_chronological(self) -> None:
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'development', '{}', 'hash', CURRENT_TIMESTAMP, NULL)"
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-01-01', 'test', 'snapshot-hash')
            """
        )
        self.connection.execute(
            """
            INSERT INTO backtest_runs(
                id, strategy_version_id, universe_snapshot_id,
                dataset_version, dataset_sha256, feature_set_version,
                status, survivorship_biased, round_trip_cost_bps
            ) VALUES (
                'run-1', 'strategy-v0', 1,
                'bars-v1', 'dataset-hash', 'features-v0',
                'running', 1, 10
            )
            """
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO backtest_splits(
                    backtest_run_id, split_index,
                    train_start, train_end, validation_start, validation_end,
                    test_start, test_end
                ) VALUES (
                    'run-1', 0,
                    '2025-01-01', '2025-12-31',
                    '2025-12-01', '2026-01-31',
                    '2026-02-01', '2026-03-31'
                )
                """
            )

    def test_migrations_are_idempotent(self) -> None:
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.assertEqual(apply_migrations(self.connection, MIGRATIONS_DIR), [])

    def test_partial_unique_index_prevents_duplicate_open_lots(self) -> None:
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self._seed_trade_dependencies()

        self.connection.execute(
            """
            INSERT INTO paper_trade_lots(
                id, signal_id, strategy_version_id, instrument_id,
                horizon_trading_days, entry_order_id, status,
                entry_notional_usd
            ) VALUES ('lot-1', 'signal-1', 'strategy-v0', 1, 21, 'order-1', 'open', 10)
            """
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO paper_trade_lots(
                    id, signal_id, strategy_version_id, instrument_id,
                    horizon_trading_days, entry_order_id, status,
                    entry_notional_usd
                ) VALUES ('lot-2', 'signal-2', 'strategy-v0', 1, 21, 'order-2', 'pending', 10)
                """
            )

    def _seed_trade_dependencies(self) -> None:
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
            ) VALUES (1, 'sp500', '2026-01-02', 'test', 'snapshot-hash')
            """
        )
        self.connection.execute(
            """
            INSERT INTO feature_snapshots(
                id, instrument_id, as_of, feature_set_version,
                features_json, data_completeness
            ) VALUES (1, 1, '2026-01-02T14:45:00Z', 'features-v0', '{}', 100)
            """
        )
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-1', 'strategy-v0', 1, 'open',
                '2026-01-02T14:45:00Z', '2026-01-02T14:45:00Z', 'succeeded'
            )
            """
        )
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-2', 'strategy-v0', 1, 'close',
                '2026-01-02T21:15:00Z', '2026-01-02T21:15:00Z', 'succeeded'
            )
            """
        )
        for signal_id, scan_id, horizon in (
            ("signal-1", "scan-1", 21),
            ("signal-2", "scan-2", 21),
        ):
            self.connection.execute(
                """
                INSERT INTO signals(
                    id, scan_run_id, strategy_version_id, instrument_id,
                    feature_snapshot_id, horizon_trading_days, as_of,
                    opportunity_score, data_completeness, risk_level,
                    decision, explanation
                ) VALUES (?, ?, 'strategy-v0', 1, 1, ?,
                    '2026-01-02T14:45:00Z', 85, 100, 'low',
                    'qualified', 'test')
                """,
                (signal_id, scan_id, horizon),
            )
        for order_id, signal_id in (("order-1", "signal-1"), ("order-2", "signal-2")):
            self.connection.execute(
                """
                INSERT INTO paper_orders(
                    id, signal_id, client_order_id, side, order_type,
                    time_in_force, notional_usd, status
                ) VALUES (?, ?, ?, 'buy', 'market', 'day', 10, 'pending')
                """,
                (order_id, signal_id, f"client-{order_id}"),
            )


if __name__ == "__main__":
    unittest.main()
