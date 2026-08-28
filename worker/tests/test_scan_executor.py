from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.features import DailyBar, FundamentalInputs
from stock_watch_worker.http import ProviderError
from stock_watch_worker.scan_data import CandidateData, ScanInputs
from stock_watch_worker.scan_executor import execute_scan


STRATEGY_PATH = Path(__file__).resolve().parents[1] / "config" / "strategy-v0.json"
NOW = datetime(2026, 8, 20, 20, 16, tzinfo=timezone.utc)


def _bars(daily_return: float, sessions: int = 220) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    close = 100.0
    result: list[DailyBar] = []
    for index in range(sessions):
        close *= 1 + daily_return
        result.append(
            DailyBar(
                session=(start + timedelta(days=index)).isoformat(),
                open=close * 0.999,
                high=close * 1.003,
                low=close * 0.997,
                close=close,
                volume=2_000_000,
            )
        )
    return tuple(result)


class FakeBroker:
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def get_order_by_client_order_id(self, client_order_id: str) -> Mapping[str, Any]:
        raise ProviderError("alpaca-paper", 404, "not found", retryable=False)

    def submit_notional_market_buy(
        self,
        *,
        symbol: str,
        notional_usd: float,
        client_order_id: str,
    ) -> Mapping[str, Any]:
        self.submissions.append(client_order_id)
        return {
            "id": f"broker-{len(self.submissions)}",
            "status": "new",
            "submitted_at": "2026-08-20T20:16:00Z",
        }


class ScanExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)

    def tearDown(self) -> None:
        self.connection.close()

    def test_persists_explainable_signals_and_is_idempotent(self) -> None:
        self._seed("development")
        inputs = self._complete_inputs()

        first = execute_scan(self.connection, inputs=inputs, now=NOW)
        second = execute_scan(self.connection, inputs=inputs, now=NOW)

        self.assertEqual(first.status, "succeeded")
        self.assertEqual(first.candidates_scored, 1)
        self.assertEqual(first.signals_created, 4)
        self.assertEqual(first.qualified_signals, 4)
        self.assertEqual(second.signals_created, 0)
        self.assertEqual(second.signals_existing, 4)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM feature_snapshots").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 4
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM signal_components").fetchone()[0],
            24,
        )
        signal = self.connection.execute(
            "SELECT * FROM signals ORDER BY horizon_trading_days LIMIT 1"
        ).fetchone()
        self.assertEqual(signal["decision"], "qualified")
        self.assertIn("Strongest available pillars", signal["explanation"])
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0], 0
        )

    def test_paper_strategy_automatically_routes_qualified_signals(self) -> None:
        self._seed("paper")
        broker = FakeBroker()

        result = execute_scan(
            self.connection,
            inputs=self._complete_inputs(),
            now=NOW,
            broker=broker,
        )

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.qualified_signals, 4)
        self.assertGreaterEqual(result.order_intents_created, 2)
        self.assertEqual(
            result.order_intents_created + result.order_intents_rejected, 4
        )
        self.assertEqual(result.broker_orders_reconciled, result.order_intents_created)
        self.assertEqual(len(broker.submissions), result.order_intents_created)
        open_notional = self.connection.execute(
            """
            SELECT SUM(entry_notional_usd) FROM paper_trade_lots
            WHERE status IN ('pending', 'open', 'closing')
            """
        ).fetchone()[0]
        self.assertLessEqual(open_notional, 30)
        self.assertTrue(
            all(
                row["status"] == "accepted"
                for row in self.connection.execute("SELECT status FROM paper_orders")
            )
        )

    def test_missing_candidate_history_is_audited_and_scan_is_partial(self) -> None:
        self._seed("development")
        complete = self._complete_inputs()
        broken = ScanInputs(
            scan_run_id=complete.scan_run_id,
            scan_type=complete.scan_type,
            data_cutoff=complete.data_cutoff,
            spy_bars=complete.spy_bars,
            candidates=(
                CandidateData(
                    instrument_id=1,
                    symbol="AAPL",
                    bars=(),
                    fundamentals=None,
                    news_sentiments=(),
                    news_coverage_complete=False,
                    source_refs={},
                ),
            ),
        )

        result = execute_scan(self.connection, inputs=broken, now=NOW)

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.candidate_failures, 1)
        event = self.connection.execute(
            "SELECT payload_json FROM audit_events WHERE event_type = 'scan_candidate_failed'"
        ).fetchone()
        self.assertIn("stock history is required", event["payload_json"])

    def test_missing_spy_fails_entire_scan(self) -> None:
        self._seed("development")
        complete = self._complete_inputs()
        broken = ScanInputs(
            scan_run_id=complete.scan_run_id,
            scan_type=complete.scan_type,
            data_cutoff=complete.data_cutoff,
            spy_bars=(),
            candidates=complete.candidates,
        )

        with self.assertRaisesRegex(ValueError, "SPY"):
            execute_scan(self.connection, inputs=broken, now=NOW)
        status = self.connection.execute(
            "SELECT status FROM scan_runs WHERE id = 'scan-1'"
        ).fetchone()[0]
        self.assertEqual(status, "failed")

    def _seed(self, status: str) -> None:
        config = json.loads(STRATEGY_PATH.read_text(encoding="utf-8"))
        canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
        self.connection.execute(
            """
            INSERT INTO strategy_versions(
                id, name, status, config_json, config_sha256
            ) VALUES ('sp500-long-v0', 'fixture', ?, ?, 'strategy-hash')
            """,
            (status, canonical),
        )
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
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-08-20', 'fixture', 'snapshot')
            """
        )
        self.connection.execute("INSERT INTO universe_memberships VALUES (1, 1)")
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-1', 'sp500-long-v0', 1, 'close',
                '2026-08-20T20:15:00Z', '2026-08-20T20:15:00Z', 'queued'
            )
            """
        )
        if status == "paper":
            cursor = self.connection.execute(
                """
                INSERT INTO broker_account_snapshots(
                    captured_at, broker, account_id, status, currency, cash,
                    equity, long_market_value, trading_blocked, account_blocked,
                    trade_suspended, raw_json
                ) VALUES ('2026-08-20T20:16:00Z', 'alpaca-paper', 'account-1',
                          'ACTIVE', 'USD', 100000, 100000, 0, 0, 0, 0, '{}')
                """
            )
            self.connection.execute(
                """
                INSERT INTO broker_reconciliations(
                    captured_at, account_snapshot_id, status,
                    expected_positions_json, actual_positions_json,
                    discrepancies_json, corporate_actions_json
                ) VALUES ('2026-08-20T20:16:00Z', ?, 'matched', '{}', '{}', '[]', '[]')
                """,
                (cursor.lastrowid,),
            )
        self.connection.commit()

    def _complete_inputs(self) -> ScanInputs:
        fundamentals = FundamentalInputs(
            as_of="2026-08-20T20:15:00Z",
            revenue_growth=0.20,
            net_margin=0.18,
            free_cash_flow_margin=0.15,
            debt_to_equity=0.5,
            price_to_earnings=18,
            free_cash_flow_yield=0.06,
        )
        return ScanInputs(
            scan_run_id="scan-1",
            scan_type="close",
            data_cutoff="2026-08-20T20:15:00Z",
            spy_bars=_bars(0.0005),
            candidates=(
                CandidateData(
                    instrument_id=1,
                    symbol="AAPL",
                    bars=_bars(0.002),
                    fundamentals=fundamentals,
                    news_sentiments=(0.4, 0.6),
                    news_coverage_complete=True,
                    source_refs={"fixture": True},
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
