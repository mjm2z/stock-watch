from __future__ import annotations

import unittest
from datetime import date, timedelta

from stock_watch_worker.backtest import (
    BacktestSignal,
    make_walk_forward_splits,
    simulate_close_signals,
)
from stock_watch_worker.domain import RiskLevel
from stock_watch_worker.features import DailyBar


def _bars(symbol_return: float = 0.01, sessions: int = 15) -> list[DailyBar]:
    result: list[DailyBar] = []
    start = date(2026, 1, 1)
    for index in range(sessions):
        open_price = 100 + index * symbol_return * 100
        result.append(
            DailyBar(
                session=(start + timedelta(days=index)).isoformat(),
                open=open_price,
                high=open_price * 1.02,
                low=open_price * 0.99,
                close=open_price * 1.01,
                volume=1_000_000,
            )
        )
    return result


def _signal(session: str, *, symbol: str = "AAPL", horizon: int = 5) -> BacktestSignal:
    return BacktestSignal(
        symbol=symbol,
        signal_session=session,
        horizon_trading_days=horizon,
        opportunity_score=85,
        risk_level=RiskLevel.LOW,
        notional_usd=10,
    )


class BacktestTests(unittest.TestCase):
    def test_close_signal_enters_next_open_and_exits_at_horizon_close(self) -> None:
        stock = _bars(symbol_return=0.01)
        spy = _bars(symbol_return=0.002)
        result = simulate_close_signals(
            signals=[_signal(stock[0].session)],
            bars_by_symbol={"AAPL": stock},
            spy_bars=spy,
            round_trip_cost_bps=10,
        )

        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.entry_session, stock[1].session)
        self.assertEqual(trade.exit_session, stock[5].session)
        self.assertEqual(trade.entry_price, stock[1].open)
        self.assertEqual(trade.exit_price, stock[5].close)
        self.assertAlmostEqual(trade.quantity, 10 / stock[1].open)
        self.assertAlmostEqual(trade.pnl_usd, 10 * trade.outcome.net_return)
        self.assertTrue(trade.outcome.beat_spy)
        self.assertEqual(result.summary.observations if result.summary else 0, 1)

    def test_rejects_overlapping_lot_but_allows_signal_on_prior_exit_close(self) -> None:
        stock = _bars()
        result = simulate_close_signals(
            signals=[
                _signal(stock[0].session),
                _signal(stock[2].session),
                _signal(stock[5].session),
            ],
            bars_by_symbol={"AAPL": stock},
            spy_bars=_bars(symbol_return=0.002),
        )

        self.assertEqual(len(result.trades), 2)
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejected[0].reason, "duplicate_open_lot")
        self.assertEqual(result.trades[1].entry_session, stock[6].session)

    def test_rejection_reasons_are_explicit(self) -> None:
        stock = _bars(sessions=6)
        result = simulate_close_signals(
            signals=[
                _signal(stock[0].session, symbol="MISSING"),
                _signal(stock[3].session),
            ],
            bars_by_symbol={"AAPL": stock},
            spy_bars=stock,
        )

        self.assertEqual(
            [rejection.reason for rejection in result.rejected],
            ["missing_symbol_history", "insufficient_future_history"],
        )
        self.assertIsNone(result.summary)

    def test_requires_matching_spy_boundary_sessions(self) -> None:
        stock = _bars()
        spy = [bar for bar in _bars(symbol_return=0.002) if bar.session != stock[5].session]
        result = simulate_close_signals(
            signals=[_signal(stock[0].session)],
            bars_by_symbol={"AAPL": stock},
            spy_bars=spy,
        )

        self.assertEqual(result.rejected[0].reason, "missing_benchmark_boundary")

    def test_enforces_concurrent_open_notional_limit_across_horizons(self) -> None:
        stock = _bars(sessions=120)
        result = simulate_close_signals(
            signals=[
                _signal(stock[0].session, horizon=horizon)
                for horizon in (5, 21, 63, 105)
            ],
            bars_by_symbol={"AAPL": stock},
            spy_bars=_bars(symbol_return=0.002, sessions=120),
            maximum_open_notional_per_symbol_usd=30,
        )

        self.assertEqual(
            [trade.signal.horizon_trading_days for trade in result.trades],
            [5, 21, 63],
        )
        self.assertEqual(result.rejected[0].reason, "ticker_notional_limit")

    def test_validates_signal_and_bar_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "horizon"):
            _signal("2026-01-01", horizon=2)
        bars = _bars()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            simulate_close_signals(
                signals=[],
                bars_by_symbol={"AAPL": bars + [bars[-1]]},
                spy_bars=bars,
            )


class WalkForwardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sessions = [f"2026-01-{day:02d}" for day in range(1, 21)]

    def test_builds_expanding_chronological_splits(self) -> None:
        splits = make_walk_forward_splits(
            self.sessions,
            train_sessions=8,
            validation_sessions=3,
            test_sessions=3,
            step_sessions=3,
        )

        self.assertEqual(len(splits), 3)
        self.assertEqual(splits[0].train_start, "2026-01-01")
        self.assertEqual(splits[0].train_end, "2026-01-08")
        self.assertEqual(splits[0].validation_start, "2026-01-09")
        self.assertEqual(splits[0].test_start, "2026-01-12")
        self.assertEqual(splits[0].test_end, "2026-01-14")
        self.assertEqual(splits[1].train_start, "2026-01-01")
        self.assertEqual(splits[1].train_end, "2026-01-11")

    def test_supports_rolling_train_window(self) -> None:
        splits = make_walk_forward_splits(
            self.sessions,
            train_sessions=8,
            validation_sessions=3,
            test_sessions=3,
            step_sessions=3,
            expanding=False,
        )

        self.assertEqual(splits[1].train_start, "2026-01-04")
        self.assertEqual(splits[1].train_end, "2026-01-11")

    def test_validates_windows_and_sessions(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            make_walk_forward_splits(
                self.sessions,
                train_sessions=0,
                validation_sessions=2,
                test_sessions=2,
            )
        with self.assertRaisesRegex(ValueError, "duplicates"):
            make_walk_forward_splits(
                self.sessions + [self.sessions[-1]],
                train_sessions=8,
                validation_sessions=2,
                test_sessions=2,
            )


if __name__ == "__main__":
    unittest.main()
