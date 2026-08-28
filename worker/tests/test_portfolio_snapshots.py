from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.portfolio_snapshots import record_portfolio_snapshot


OBSERVED_AT = datetime(2026, 8, 20, 21, 15, tzinfo=timezone.utc)


class PortfolioSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self._seed_lots_and_bars()

    def tearDown(self) -> None:
        self.connection.close()

    def test_values_filled_cohorts_and_contribution_matched_spy(self) -> None:
        first = record_portfolio_snapshot(self.connection, observed_at=OBSERVED_AT)
        repeated = record_portfolio_snapshot(self.connection, observed_at=OBSERVED_AT)

        self.assertTrue(first.inserted)
        self.assertFalse(repeated.inserted)
        self.assertEqual(first.filled_lots, 2)
        self.assertAlmostEqual(first.contributed_capital, 20)
        self.assertAlmostEqual(first.cash, 11)
        self.assertAlmostEqual(first.market_value, 11)
        self.assertAlmostEqual(first.equity, 22)
        self.assertAlmostEqual(first.realized_pnl, 1)
        self.assertAlmostEqual(first.unrealized_pnl, 1)
        expected_spy = (10 / 500 * 520) + (10 / 505 * 515)
        self.assertAlmostEqual(first.spy_value or 0, expected_spy)
        stored = self.connection.execute("SELECT * FROM portfolio_snapshots").fetchone()
        self.assertAlmostEqual(stored["contributed_capital"], 20)
        self.assertEqual(stored["gross_exposure"], 11)

    def test_missing_benchmark_boundary_is_explicit(self) -> None:
        self.connection.execute(
            "DELETE FROM market_bars WHERE instrument_id = 3 AND timestamp = '2026-08-18'"
        )

        result = record_portfolio_snapshot(self.connection, observed_at=OBSERVED_AT)

        self.assertIsNone(result.spy_value)
        self.assertEqual(result.benchmark_missing_lots, ("lot-closed",))
        self.assertEqual(
            self.connection.execute("SELECT spy_value FROM portfolio_snapshots").fetchone()[0],
            None,
        )

    def test_same_timestamp_rejects_changed_valuation(self) -> None:
        record_portfolio_snapshot(self.connection, observed_at=OBSERVED_AT)
        self.connection.execute(
            "UPDATE market_bars SET close = 230 WHERE instrument_id = 1 AND timestamp = '2026-08-20'"
        )

        with self.assertRaisesRegex(ValueError, "immutable portfolio snapshot"):
            record_portfolio_snapshot(self.connection, observed_at=OBSERVED_AT)

    def test_partial_exit_keeps_remaining_shares_exposed(self) -> None:
        self.connection.execute("DELETE FROM paper_trade_lots WHERE id = 'lot-closed'")
        self.connection.execute(
            """
            UPDATE paper_trade_lots
            SET status = 'closing', exit_quantity = 0.02, exit_price = 210
            WHERE id = 'lot-open'
            """
        )
        self.connection.execute(
            """
            INSERT INTO paper_exit_orders(
                id, lot_id, client_order_id, quantity, status
            ) VALUES ('exit-partial', 'lot-open', 'exit-client-partial', 0.05, 'partially_filled')
            """
        )
        self.connection.execute(
            """
            INSERT INTO paper_exit_fills(
                id, exit_order_id, broker_fill_id, filled_at,
                quantity, price, notional_usd
            ) VALUES (
                'exit-fill-partial', 'exit-partial', 'broker-fill-partial',
                '2026-08-20T13:30:00Z', 0.02, 210, 4.2
            )
            """
        )

        result = record_portfolio_snapshot(self.connection, observed_at=OBSERVED_AT)

        self.assertAlmostEqual(result.contributed_capital, 10)
        self.assertAlmostEqual(result.cash, 4.2)
        self.assertAlmostEqual(result.market_value, 6.6)
        self.assertAlmostEqual(result.equity, 10.8)
        self.assertAlmostEqual(result.realized_pnl, 0.2)
        self.assertAlmostEqual(result.unrealized_pnl, 0.6)
        expected_spy = (10 / 500 * 0.4 * 515) + (10 / 500 * 0.6 * 520)
        self.assertAlmostEqual(result.spy_value or 0, expected_spy)

    def _seed_lots_and_bars(self) -> None:
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'paper', '{}', 'hash', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        self.connection.executemany(
            "INSERT INTO instruments(id, symbol, active, fractionable) VALUES (?, ?, 1, 1)",
            ((1, "AAPL"), (2, "MSFT"), (3, "SPY")),
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-08-17', 'fixture', 'snapshot')
            """
        )
        self.connection.executemany(
            """
            INSERT INTO feature_snapshots(
                id, instrument_id, as_of, feature_set_version,
                features_json, data_completeness
            ) VALUES (?, ?, '2026-08-17T13:45:00Z', 'features-v0', '{}', 100)
            """,
            ((1, 1), (2, 2)),
        )
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-1', 'strategy-v0', 1, 'open',
                '2026-08-17T13:45:00Z', '2026-08-17T13:45:00Z', 'succeeded'
            )
            """
        )
        for signal_id, instrument_id, feature_id in (
            ("signal-open", 1, 1),
            ("signal-closed", 2, 2),
        ):
            self.connection.execute(
                """
                INSERT INTO signals(
                    id, scan_run_id, strategy_version_id, instrument_id,
                    feature_snapshot_id, horizon_trading_days, as_of,
                    opportunity_score, data_completeness, risk_level,
                    decision, explanation
                ) VALUES (?, 'scan-1', 'strategy-v0', ?, ?, 5,
                    '2026-08-17T13:45:00Z', 90, 100, 'low', 'qualified', 'fixture')
                """,
                (signal_id, instrument_id, feature_id),
            )
        for order_id, signal_id, client_id in (
            ("entry-open", "signal-open", "client-open"),
            ("entry-closed", "signal-closed", "client-closed"),
        ):
            self.connection.execute(
                """
                INSERT INTO paper_orders(
                    id, signal_id, client_order_id, broker_order_id, side,
                    order_type, time_in_force, notional_usd, status
                ) VALUES (?, ?, ?, ?, 'buy', 'market', 'day', 10, 'filled')
                """,
                (order_id, signal_id, f"{client_id}", f"broker-{order_id}"),
            )
        self.connection.execute(
            """
            INSERT INTO paper_trade_lots(
                id, signal_id, strategy_version_id, instrument_id,
                horizon_trading_days, entry_order_id, status, opened_at,
                entry_quantity, entry_price, entry_notional_usd
            ) VALUES (
                'lot-open', 'signal-open', 'strategy-v0', 1, 5,
                'entry-open', 'open', '2026-08-17T13:45:00Z', 0.05, 200, 10
            )
            """
        )
        self.connection.execute(
            """
            INSERT INTO paper_trade_lots(
                id, signal_id, strategy_version_id, instrument_id,
                horizon_trading_days, entry_order_id, status, opened_at,
                closed_at, entry_quantity, entry_price, entry_notional_usd,
                exit_quantity, exit_price, realized_return
            ) VALUES (
                'lot-closed', 'signal-closed', 'strategy-v0', 2, 5,
                'entry-closed', 'closed', '2026-08-18T13:45:00Z',
                '2026-08-20T13:30:00Z', 0.1, 100, 10, 0.1, 110, 0.1
            )
            """
        )
        bars = (
            (1, "2026-08-17", 200, 200),
            (1, "2026-08-20", 218, 220),
            (2, "2026-08-18", 100, 100),
            (2, "2026-08-20", 109, 110),
            (3, "2026-08-17", 500, 500),
            (3, "2026-08-18", 505, 507),
            (3, "2026-08-20", 515, 520),
        )
        for instrument_id, session, open_price, close_price in bars:
            self.connection.execute(
                """
                INSERT INTO market_bars(
                    instrument_id, timestamp, timeframe, open, high, low, close,
                    volume, adjustment, provider
                ) VALUES (?, ?, '1Day', ?, ?, ?, ?, 1000000, 'all', 'alpaca')
                """,
                (
                    instrument_id,
                    session,
                    open_price,
                    max(open_price, close_price),
                    min(open_price, close_price),
                    close_price,
                ),
            )
        self.connection.commit()


if __name__ == "__main__":
    unittest.main()
