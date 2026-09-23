from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.forward_outcomes import evaluate_forward_outcomes


OBSERVED_AT = datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc)


class ForwardOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self._seed_signals_and_bars()

    def tearDown(self) -> None:
        self.connection.close()

    def test_persists_mature_outcome_on_aligned_next_session_window(self) -> None:
        first = evaluate_forward_outcomes(
            self.connection,
            observed_at=OBSERVED_AT,
            round_trip_cost_bps=10,
        )
        repeated = evaluate_forward_outcomes(
            self.connection,
            observed_at=OBSERVED_AT,
            round_trip_cost_bps=10,
        )

        self.assertEqual(first.candidates, 2)
        self.assertEqual(first.completed, 1)
        self.assertEqual(first.pending_history, 1)
        self.assertEqual(repeated.candidates, 1)
        outcome = self.connection.execute(
            "SELECT * FROM signal_outcomes WHERE signal_id = 'signal-5'"
        ).fetchone()
        self.assertEqual(outcome["entry_session"], "2026-08-18")
        self.assertEqual(outcome["exit_session"], "2026-08-24")
        self.assertAlmostEqual(outcome["gross_return"], 0.10)
        self.assertAlmostEqual(outcome["net_return"], 0.099)
        self.assertEqual(outcome["terminal_at_least_5"], 1)
        self.assertEqual(outcome["beat_spy"], 1)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'signal_outcome_completed'"
            ).fetchone()[0],
            1,
        )

    def test_rejected_signal_with_shadow_assessment_is_evaluated(self):
        self.connection.execute("UPDATE signals SET decision='rejected' WHERE id='signal-5'")
        first=evaluate_forward_outcomes(self.connection,observed_at=OBSERVED_AT)
        self.assertEqual(first.completed,0)
        self.connection.execute("INSERT INTO shadow_assessments VALUES ('signal-5','baseline-v1',70,0,'[]','{}','2026-08-17')")
        second=evaluate_forward_outcomes(self.connection,observed_at=OBSERVED_AT)
        self.assertEqual(second.completed,1)
        self.assertAlmostEqual(self.connection.execute("SELECT net_return FROM signal_outcomes WHERE signal_id='signal-5'").fetchone()[0],.099)

    def test_missing_stock_session_is_explicit_and_not_persisted(self) -> None:
        self.connection.execute(
            "DELETE FROM market_bars WHERE instrument_id = 1 AND timestamp = '2026-08-20'"
        )

        result = evaluate_forward_outcomes(
            self.connection,
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(result.completed, 0)
        self.assertEqual(result.missing_history, 1)
        self.assertEqual(result.pending_history, 1)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0],
            0,
        )

    def test_intraday_outcome_remains_pending(self):
        result = evaluate_forward_outcomes(self.connection,
            observed_at=datetime(2026, 8, 24, 14, tzinfo=timezone.utc))
        self.assertEqual(result.completed, 0)
        state = self.connection.execute("SELECT state FROM signal_evaluations WHERE signal_id='signal-5'").fetchone()[0]
        self.assertEqual(state, "waiting_for_close")

    def test_old_partial_bar_is_not_finalized_after_close(self):
        self.connection.execute("UPDATE market_bars SET last_observed_at='2026-08-24T14:00:00Z' WHERE timestamp='2026-08-24'")
        result = evaluate_forward_outcomes(self.connection, observed_at=OBSERVED_AT)
        self.assertEqual(result.completed, 0)
        self.assertEqual(result.missing_history, 1)

    def test_missing_calendar_does_not_guess_session_boundaries(self):
        self.connection.execute("DELETE FROM market_sessions")
        result = evaluate_forward_outcomes(self.connection, observed_at=OBSERVED_AT)
        self.assertEqual(result.completed, 0)
        self.assertEqual(result.missing_history, 2)

    def test_early_close_uses_exchange_calendar(self):
        self.connection.execute("UPDATE market_sessions SET closes_at='2026-08-24T17:00:00Z' WHERE trading_date='2026-08-24'")
        self.connection.execute("UPDATE market_bars SET last_observed_at='2026-08-24T17:20:00Z' WHERE timestamp='2026-08-24'")
        result = evaluate_forward_outcomes(self.connection,
            observed_at=datetime(2026, 8, 24, 17, 30, tzinfo=timezone.utc))
        self.assertEqual(result.completed, 1)

    def test_rejects_naive_observation_timestamp(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone"):
            evaluate_forward_outcomes(
                self.connection,
                observed_at=datetime(2026, 8, 24, 17, 0),
            )

    def _seed_signals_and_bars(self) -> None:
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'development', '{}', 'hash', CURRENT_TIMESTAMP, NULL)"
        )
        self.connection.executemany(
            "INSERT INTO instruments(id, symbol) VALUES (?, ?)",
            ((1, "AAPL"), (2, "SPY")),
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
            ) VALUES (1, 1, '2026-08-17T20:15:00Z', 'features-v0', '{}', 100)
            """
        )
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-1', 'strategy-v0', 1, 'close',
                '2026-08-17T20:15:00Z', '2026-08-17T20:15:00Z', 'succeeded'
            )
            """
        )
        for signal_id, horizon in (("signal-5", 5), ("signal-21", 21)):
            self.connection.execute(
                """
                INSERT INTO signals(
                    id, scan_run_id, strategy_version_id, instrument_id,
                    feature_snapshot_id, horizon_trading_days, as_of,
                    opportunity_score, data_completeness, risk_level,
                    decision, explanation
                ) VALUES (?, 'scan-1', 'strategy-v0', 1, 1, ?,
                    '2026-08-17T20:15:00Z', 90, 100, 'low', 'qualified', 'fixture')
                """,
                (signal_id, horizon),
            )
        sessions = ("2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24")
        stock = (
            (100, 102, 99, 101),
            (102, 105, 101, 104),
            (104, 108, 103, 107),
            (107, 111, 106, 109),
            (109, 112, 108, 110),
        )
        spy = (
            (500, 502, 498, 501),
            (502, 505, 500, 504),
            (504, 507, 503, 506),
            (506, 510, 505, 508),
            (508, 512, 507, 510),
        )
        for instrument_id, values in ((1, stock), (2, spy)):
            for session, prices in zip(sessions, values, strict=True):
                self.connection.execute(
                    """
                    INSERT INTO market_bars(
                        instrument_id, timestamp, timeframe, open, high,
                        low, close, volume, adjustment, provider
                    ) VALUES (?, ?, '1Day', ?, ?, ?, ?, 1000000, 'all', 'alpaca')
                    """,
                    (instrument_id, session, *prices),
                )
        for session in sessions:
            self.connection.execute(
                "INSERT INTO market_sessions(trading_date,provider,opens_at,closes_at) "
                "VALUES (?, 'alpaca-paper', ?, ?)",
                (session, session + 'T13:30:00Z', session + 'T20:00:00Z'),
            )
        self.connection.execute("UPDATE market_bars SET last_observed_at=timestamp || 'T20:30:00Z'")
        self.connection.commit()


if __name__ == "__main__":
    unittest.main()
