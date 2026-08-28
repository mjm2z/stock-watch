from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone

from stock_watch_worker.broker_reconciliation import capture_and_reconcile_broker
from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.providers.alpaca import (
    AlpacaAccount,
    AlpacaAccountActivity,
    AlpacaPosition,
)


NOW = datetime(2026, 8, 20, 21, 15, tzinfo=timezone.utc)


class FakeBroker:
    def __init__(
        self,
        *,
        positions: list[AlpacaPosition] | None = None,
        activities: list[AlpacaAccountActivity] | None = None,
        blocked: bool = False,
    ) -> None:
        raw = {
            "id": "paper-account-1",
            "status": "ACTIVE",
            "currency": "USD",
            "cash": "100000",
            "equity": "100000",
            "long_market_value": "0",
            "trading_blocked": blocked,
            "account_blocked": False,
            "trade_suspended_by_user": False,
        }
        self.account = AlpacaAccount(
            "paper-account-1",
            "ACTIVE",
            "USD",
            100000,
            100000,
            0,
            blocked,
            False,
            False,
            raw,
        )
        self.positions = positions or []
        self.activities = activities or []
        self.after_values: list[str | None] = []
        self.account_calls = 0

    def get_account(self) -> AlpacaAccount:
        self.account_calls += 1
        return self.account

    def get_positions(self) -> list[AlpacaPosition]:
        return self.positions

    def get_non_trade_activities(
        self, *, after: str | None = None
    ) -> list[AlpacaAccountActivity]:
        self.after_values.append(after)
        return self.activities


class BrokerReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)

    def tearDown(self) -> None:
        self.connection.close()

    def test_empty_internal_and_broker_accounts_match_idempotently(self) -> None:
        broker = FakeBroker()

        first = capture_and_reconcile_broker(
            self.connection, broker=broker, captured_at=NOW
        )
        second = capture_and_reconcile_broker(
            self.connection, broker=broker, captured_at=NOW
        )

        self.assertEqual(first.status, "matched")
        self.assertTrue(first.inserted)
        self.assertFalse(second.inserted)
        self.assertEqual(broker.account_calls, 1)

    def test_unexpected_position_is_drift_with_corporate_action_evidence(self) -> None:
        raw_position = {
            "asset_id": "asset-1",
            "symbol": "AAPL",
            "qty": "0.05",
            "market_value": "10",
            "current_price": "200",
            "cost_basis": "10",
            "side": "long",
        }
        position = AlpacaPosition(
            "asset-1", "AAPL", 0.05, 10, 200, 10, "long", raw_position
        )
        raw_activity = {
            "id": "split-1",
            "activity_type": "SSP",
            "date": "2026-08-20",
            "symbol": "AAPL",
            "qty": "0.05",
        }
        activity = AlpacaAccountActivity(
            "split-1", "SSP", "2026-08-20", "AAPL", None, 0.05, None, raw_activity
        )

        result = capture_and_reconcile_broker(
            self.connection,
            broker=FakeBroker(positions=[position], activities=[activity]),
            captured_at=NOW,
        )

        self.assertEqual(result.status, "drift")
        self.assertEqual(result.discrepancies[0]["kind"], "unexpected_broker_position")
        self.assertEqual(result.corporate_actions[0]["activity_type"], "SSP")
        self.assertEqual(result.activities_inserted, 1)

    def test_open_and_partially_exited_lots_aggregate_to_broker_quantity(self) -> None:
        self.connection.execute("PRAGMA foreign_keys = OFF")
        self.connection.execute(
            "INSERT INTO instruments(id, symbol, active, fractionable) VALUES (1, 'AAPL', 1, 1)"
        )
        self.connection.executemany(
            """
            INSERT INTO paper_trade_lots(
                id, signal_id, strategy_version_id, instrument_id,
                horizon_trading_days, entry_order_id, status, entry_quantity,
                entry_price, entry_notional_usd, exit_quantity
            ) VALUES (?, ?, 'strategy-v0', 1, ?, ?, ?, ?, 200, ?, ?)
            """,
            (
                ("lot-1", "signal-1", 5, "order-1", "open", 0.03, 6, None),
                ("lot-2", "signal-2", 21, "order-2", "closing", 0.04, 8, 0.01),
            ),
        )
        self.connection.commit()
        self.connection.execute("PRAGMA foreign_keys = ON")
        raw = {
            "asset_id": "asset-1",
            "symbol": "AAPL",
            "qty": "0.06",
            "market_value": "12",
            "current_price": "200",
            "cost_basis": "12",
            "side": "long",
        }
        position = AlpacaPosition(
            "asset-1", "AAPL", 0.06, 12, 200, 12, "long", raw
        )

        result = capture_and_reconcile_broker(
            self.connection,
            broker=FakeBroker(positions=[position]),
            captured_at=NOW,
        )

        self.assertEqual(result.status, "matched")
        self.assertAlmostEqual(result.expected_positions["AAPL"], 0.06)

    def test_account_restriction_blocks_even_when_positions_match(self) -> None:
        result = capture_and_reconcile_broker(
            self.connection, broker=FakeBroker(blocked=True), captured_at=NOW
        )

        self.assertEqual(result.status, "blocked")
        self.assertIn("trading_blocked", result.discrepancies[-1]["reasons"])


if __name__ == "__main__":
    unittest.main()
