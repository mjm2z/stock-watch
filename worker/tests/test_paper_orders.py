from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from typing import Any, Mapping

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.http import ProviderError
from stock_watch_worker.paper_orders import (
    create_order_intent,
    submit_or_reconcile_order,
)


NOW = datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc)


class FakeBroker:
    def __init__(
        self,
        *,
        existing: Mapping[str, Any] | None = None,
        submitted: Mapping[str, Any] | None = None,
        lookup_error: ProviderError | None = None,
    ) -> None:
        self.existing = existing
        self.submitted = submitted or {"id": "broker-1", "status": "new"}
        self.lookup_error = lookup_error
        self.lookup_calls = 0
        self.submit_calls = 0

    def get_order_by_client_order_id(self, client_order_id: str) -> Mapping[str, Any]:
        self.lookup_calls += 1
        if self.lookup_error:
            raise self.lookup_error
        if self.existing is None:
            raise ProviderError("alpaca-paper", 404, "not found", retryable=False)
        return self.existing

    def submit_notional_market_buy(
        self,
        *,
        symbol: str,
        notional_usd: float,
        client_order_id: str,
    ) -> Mapping[str, Any]:
        self.submit_calls += 1
        return self.submitted


class PaperOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self._seed_dependencies()

    def tearDown(self) -> None:
        self.connection.close()

    def test_creates_idempotent_intent_before_broker_submission(self) -> None:
        first = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )
        second = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )

        self.assertEqual(first.action, "created")
        self.assertEqual(second.action, "existing")
        self.assertEqual(first.order_id, second.order_id)
        order = self.connection.execute("SELECT * FROM paper_orders").fetchone()
        lot = self.connection.execute("SELECT * FROM paper_trade_lots").fetchone()
        self.assertEqual(order["status"], "pending")
        self.assertEqual(lot["status"], "pending")
        self.assertEqual(lot["entry_notional_usd"], 10)

    def test_rejects_duplicate_horizon_and_ticker_exposure_limit(self) -> None:
        create_order_intent(self.connection, signal_id="signal-5", notional_usd=15)
        duplicate = create_order_intent(
            self.connection, signal_id="signal-5-other", notional_usd=10
        )
        create_order_intent(self.connection, signal_id="signal-21", notional_usd=15)
        capped = create_order_intent(
            self.connection, signal_id="signal-63", notional_usd=5
        )

        self.assertEqual(duplicate.reason, "duplicate_open_lot")
        self.assertEqual(capped.reason, "ticker_notional_limit")

    def test_requires_explicit_paper_promotion_and_fractionable_asset(self) -> None:
        self.connection.execute(
            "UPDATE strategy_versions SET status = 'development' WHERE id = 'strategy-v0'"
        )
        development = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )
        self.assertEqual(development.reason, "strategy_not_promoted_to_paper")

        self.connection.execute(
            "UPDATE strategy_versions SET status = 'paper' WHERE id = 'strategy-v0'"
        )
        self.connection.execute("UPDATE instruments SET fractionable = 0 WHERE id = 1")
        not_fractionable = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )
        self.assertEqual(not_fractionable.reason, "instrument_not_fractionable")

    def test_requires_latest_broker_positions_to_match(self) -> None:
        self.connection.execute("DELETE FROM broker_reconciliations")
        self._seed_reconciliation("matched", "2026-08-20T13:00:00Z")
        stale = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )
        self.assertEqual(stale.reason, "broker_reconciliation_stale")

        self.connection.execute("DELETE FROM broker_reconciliations")
        unavailable = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )
        self.assertEqual(unavailable.reason, "broker_reconciliation_unavailable")

        self._seed_reconciliation("drift", "2026-08-20T14:01:00Z")
        drift = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )
        self.assertEqual(drift.reason, "broker_position_drift")

    def test_reconciles_before_submit_then_submits_if_absent(self) -> None:
        intent = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )
        broker = FakeBroker()

        result = submit_or_reconcile_order(
            self.connection, order_id=intent.order_id or "", broker=broker, now=NOW
        )

        self.assertEqual((broker.lookup_calls, broker.submit_calls), (1, 1))
        self.assertEqual(result.status, "accepted")
        order = self.connection.execute(
            "SELECT status, submitted_at FROM paper_orders WHERE id = ?", (intent.order_id,)
        ).fetchone()
        self.assertEqual(order["status"], "accepted")
        self.assertEqual(order["submitted_at"], "2026-08-20T14:00:00Z")

    def test_crash_recovery_finds_existing_fill_without_duplicate_submit(self) -> None:
        intent = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )
        broker = FakeBroker(
            existing={
                "id": "broker-existing",
                "status": "filled",
                "filled_qty": "0.05",
                "filled_avg_price": "200",
                "filled_at": "2026-08-20T14:01:00Z",
            }
        )

        result = submit_or_reconcile_order(
            self.connection, order_id=intent.order_id or "", broker=broker, now=NOW
        )

        self.assertEqual(broker.submit_calls, 0)
        self.assertEqual(result.status, "filled")
        lot = self.connection.execute(
            "SELECT status, entry_quantity, entry_price FROM paper_trade_lots"
        ).fetchone()
        self.assertEqual(lot["status"], "open")
        self.assertEqual(lot["entry_quantity"], 0.05)
        self.assertEqual(lot["entry_price"], 200)
        fill = self.connection.execute(
            "SELECT quantity, price, notional_usd FROM paper_fills"
        ).fetchone()
        self.assertEqual(fill["quantity"], 0.05)
        self.assertEqual(fill["price"], 200)
        self.assertEqual(fill["notional_usd"], 10)

    def test_provider_failure_is_recorded_and_left_reconcilable(self) -> None:
        intent = create_order_intent(
            self.connection, signal_id="signal-5", notional_usd=10
        )
        broker = FakeBroker(
            lookup_error=ProviderError(
                "alpaca-paper", 503, "unavailable", retryable=True
            )
        )

        with self.assertRaises(ProviderError):
            submit_or_reconcile_order(
                self.connection, order_id=intent.order_id or "", broker=broker, now=NOW
            )
        order = self.connection.execute(
            "SELECT status, error FROM paper_orders WHERE id = ?", (intent.order_id,)
        ).fetchone()
        self.assertEqual(order["status"], "pending")
        self.assertIn("503", order["error"])

    def _seed_dependencies(self) -> None:
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'paper', '{}', 'hash', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        self.connection.execute(
            """
            INSERT INTO instruments(id, symbol, active, fractionable)
            VALUES (1, 'AAPL', 1, 1)
            """
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-08-20', 'fixture', 'snapshot')
            """
        )
        self.connection.execute(
            """
            INSERT INTO feature_snapshots(
                id, instrument_id, as_of, feature_set_version,
                features_json, data_completeness
            ) VALUES (1, 1, '2026-08-20T13:45:00Z', 'features-v0', '{}', 100)
            """
        )
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-1', 'strategy-v0', 1, 'open',
                '2026-08-20T13:45:00Z', '2026-08-20T13:45:00Z', 'succeeded'
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
                '2026-08-20T20:15:00Z', '2026-08-20T20:15:00Z', 'succeeded'
            )
            """
        )
        for signal_id, scan_id, horizon in (
            ("signal-5", "scan-1", 5),
            ("signal-5-other", "scan-2", 5),
            ("signal-21", "scan-1", 21),
            ("signal-63", "scan-1", 63),
        ):
            self.connection.execute(
                """
                INSERT INTO signals(
                    id, scan_run_id, strategy_version_id, instrument_id,
                    feature_snapshot_id, horizon_trading_days, as_of,
                    opportunity_score, data_completeness, risk_level,
                    decision, explanation
                ) VALUES (?, ?, 'strategy-v0', 1, 1, ?,
                    '2026-08-20T13:45:00Z', 85, 100, 'low',
                    'qualified', 'fixture')
                """,
                (signal_id, scan_id, horizon),
            )
        self.connection.commit()
        self._seed_reconciliation("matched", "2026-08-20T14:00:00Z")

    def _seed_reconciliation(self, status: str, captured_at: str) -> None:
        cursor = self.connection.execute(
            """
            INSERT INTO broker_account_snapshots(
                captured_at, broker, account_id, status, currency, cash, equity,
                long_market_value, trading_blocked, account_blocked,
                trade_suspended, raw_json
            ) VALUES (?, 'alpaca-paper', 'account-1', 'ACTIVE', 'USD',
                      100000, 100000, 0, 0, 0, 0, '{}')
            """,
            (captured_at,),
        )
        self.connection.execute(
            """
            INSERT INTO broker_reconciliations(
                captured_at, account_snapshot_id, status,
                expected_positions_json, actual_positions_json,
                discrepancies_json, corporate_actions_json
            ) VALUES (?, ?, ?, '{}', '{}', '[]', '[]')
            """,
            (captured_at, cursor.lastrowid, status),
        )
        self.connection.commit()


if __name__ == "__main__":
    unittest.main()
