from __future__ import annotations

import sqlite3
import unittest
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.http import ProviderError
from stock_watch_worker.market_calendar import MarketSession
from stock_watch_worker.paper_lifecycle import (
    create_exit_intent,
    reconcile_paper_lifecycle,
    submit_or_reconcile_exit,
)


NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 21, 20, 15, tzinfo=timezone.utc)


class FakeLifecycleBroker:
    def __init__(self, existing: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.existing = dict(existing or {})
        self.buy_calls = 0
        self.sell_calls = 0

    def get_order_by_client_order_id(self, client_order_id: str) -> Mapping[str, Any]:
        if client_order_id not in self.existing:
            raise ProviderError("alpaca-paper", 404, "not found", retryable=False)
        return self.existing[client_order_id]

    def submit_notional_market_buy(
        self,
        *,
        symbol: str,
        notional_usd: Decimal | float | str,
        client_order_id: str,
    ) -> Mapping[str, Any]:
        self.buy_calls += 1
        raise AssertionError("entry submission was not expected")

    def submit_fractional_market_sell(
        self,
        *,
        symbol: str,
        quantity: Decimal | float | str,
        client_order_id: str,
    ) -> Mapping[str, Any]:
        self.sell_calls += 1
        return {
            "id": "broker-exit-1",
            "status": "filled",
            "filled_qty": str(quantity),
            "filled_avg_price": "210",
            "filled_at": "2026-08-24T13:30:01Z",
        }


class PaperLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self._seed_open_lot()

    def tearDown(self) -> None:
        self.connection.close()

    def test_mature_lot_creates_one_exit_and_closes_from_fill(self) -> None:
        broker = FakeLifecycleBroker()

        result = reconcile_paper_lifecycle(
            self.connection,
            broker=broker,
            sessions=_sessions(date(2026, 8, 17), 5),
            now=NOW,
        )
        repeated = reconcile_paper_lifecycle(
            self.connection,
            broker=broker,
            sessions=_sessions(date(2026, 8, 17), 5),
            now=NOW,
        )

        self.assertEqual(result.exit_intents_created, 1)
        self.assertEqual(result.lots_closed, 1)
        self.assertEqual(repeated.exit_intents_created, 0)
        self.assertEqual(broker.sell_calls, 1)
        lot = self.connection.execute(
            """
            SELECT status, minimum_exit_at, target_exit_at, exit_quantity,
                   exit_price, realized_return, closed_at
            FROM paper_trade_lots WHERE id = 'lot-1'
            """
        ).fetchone()
        self.assertEqual(lot["status"], "closed")
        self.assertEqual(lot["minimum_exit_at"], "2026-08-18T20:00:00Z")
        self.assertEqual(lot["target_exit_at"], "2026-08-21T20:00:00Z")
        self.assertEqual(lot["exit_quantity"], 0.05)
        self.assertEqual(lot["exit_price"], 210)
        self.assertAlmostEqual(lot["realized_return"], 0.05)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM paper_exit_fills").fetchone()[0],
            1,
        )

    def test_exit_reconciliation_finds_existing_broker_fill_before_submit(self) -> None:
        intent = create_exit_intent(self.connection, lot_id="lot-1")
        client_id = self.connection.execute(
            "SELECT client_order_id FROM paper_exit_orders WHERE id = ?",
            (intent.exit_order_id,),
        ).fetchone()[0]
        broker = FakeLifecycleBroker(
            {
                client_id: {
                    "id": "broker-existing-exit",
                    "status": "filled",
                    "filled_qty": "0.05",
                    "filled_avg_price": "190",
                    "filled_at": "2026-08-24T13:30:01Z",
                }
            }
        )

        result = submit_or_reconcile_exit(
            self.connection,
            exit_order_id=intent.exit_order_id,
            broker=broker,
            now=NOW,
        )

        self.assertEqual(result.status, "filled")
        self.assertEqual(broker.sell_calls, 0)
        lot = self.connection.execute(
            "SELECT status, realized_return FROM paper_trade_lots WHERE id = 'lot-1'"
        ).fetchone()
        self.assertEqual(lot["status"], "closed")
        self.assertAlmostEqual(lot["realized_return"], -0.05)

    def test_requires_complete_entry_fill_before_exit(self) -> None:
        self.connection.execute(
            "UPDATE paper_orders SET status = 'partially_filled' WHERE id = 'entry-1'"
        )

        with self.assertRaisesRegex(ValueError, "completely filled"):
            create_exit_intent(self.connection, lot_id="lot-1")

    def test_filled_exit_requires_fill_economics_and_rolls_back(self) -> None:
        intent = create_exit_intent(self.connection, lot_id="lot-1")
        client_id = self.connection.execute(
            "SELECT client_order_id FROM paper_exit_orders WHERE id = ?",
            (intent.exit_order_id,),
        ).fetchone()[0]
        broker = FakeLifecycleBroker(
            {client_id: {"id": "broker-bad-fill", "status": "filled"}}
        )

        with self.assertRaisesRegex(ValueError, "missing quantity or price"):
            submit_or_reconcile_exit(
                self.connection,
                exit_order_id=intent.exit_order_id,
                broker=broker,
                now=NOW,
            )

        self.assertEqual(
            self.connection.execute(
                "SELECT status FROM paper_exit_orders WHERE id = ?",
                (intent.exit_order_id,),
            ).fetchone()[0],
            "pending",
        )

    def test_rejected_exit_keeps_lot_exposed_in_closing_state(self) -> None:
        intent = create_exit_intent(self.connection, lot_id="lot-1")
        client_id = self.connection.execute(
            "SELECT client_order_id FROM paper_exit_orders WHERE id = ?",
            (intent.exit_order_id,),
        ).fetchone()[0]
        broker = FakeLifecycleBroker(
            {
                client_id: {
                    "id": "broker-rejected-exit",
                    "status": "rejected",
                    "reject_reason": "fixture rejection",
                }
            }
        )

        result = submit_or_reconcile_exit(
            self.connection,
            exit_order_id=intent.exit_order_id,
            broker=broker,
            now=NOW,
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            self.connection.execute(
                "SELECT status FROM paper_trade_lots WHERE id = 'lot-1'"
            ).fetchone()[0],
            "closing",
        )

    def _seed_open_lot(self) -> None:
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'paper', '{}', 'hash', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        self.connection.execute(
            "INSERT INTO instruments(id, symbol, active, fractionable) VALUES (1, 'AAPL', 1, 1)"
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-08-17', 'fixture', 'snapshot')
            """
        )
        self.connection.execute(
            """
            INSERT INTO feature_snapshots(
                id, instrument_id, as_of, feature_set_version,
                features_json, data_completeness
            ) VALUES (1, 1, '2026-08-17T13:45:00Z', 'features-v0', '{}', 100)
            """
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
        self.connection.execute(
            """
            INSERT INTO signals(
                id, scan_run_id, strategy_version_id, instrument_id,
                feature_snapshot_id, horizon_trading_days, as_of,
                opportunity_score, data_completeness, risk_level,
                decision, explanation
            ) VALUES (
                'signal-1', 'scan-1', 'strategy-v0', 1, 1, 5,
                '2026-08-17T13:45:00Z', 90, 100, 'low', 'qualified', 'fixture'
            )
            """
        )
        self.connection.execute(
            """
            INSERT INTO paper_orders(
                id, signal_id, client_order_id, broker_order_id, side,
                order_type, time_in_force, notional_usd, status, submitted_at
            ) VALUES (
                'entry-1', 'signal-1', 'entry-client-1', 'broker-entry-1', 'buy',
                'market', 'day', 10, 'filled', '2026-08-17T13:30:00Z'
            )
            """
        )
        self.connection.execute(
            """
            INSERT INTO paper_trade_lots(
                id, signal_id, strategy_version_id, instrument_id,
                horizon_trading_days, entry_order_id, status, opened_at,
                entry_quantity, entry_price, entry_notional_usd
            ) VALUES (
                'lot-1', 'signal-1', 'strategy-v0', 1, 5, 'entry-1', 'open',
                '2026-08-17T13:30:01Z', 0.05, 200, 10
            )
            """
        )
        self.connection.commit()


def _sessions(start: date, count: int) -> tuple[MarketSession, ...]:
    sessions: list[MarketSession] = []
    current = start
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(
                MarketSession(
                    trading_date=current,
                    opens_at=datetime.combine(current, time(9, 30), NEW_YORK),
                    closes_at=datetime.combine(current, time(16, 0), NEW_YORK),
                )
            )
        current = date.fromordinal(current.toordinal() + 1)
    return tuple(sessions)


if __name__ == "__main__":
    unittest.main()
