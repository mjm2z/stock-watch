from __future__ import annotations

import unittest
from datetime import date, timedelta

from stock_watch_worker.backtest import BacktestSignal, simulate_close_signals
from stock_watch_worker.backtest_portfolio import summarize_unlimited_funding_portfolio
from stock_watch_worker.domain import RiskLevel
from stock_watch_worker.features import DailyBar


def _bars(*, daily_step: float, sessions: int = 30) -> list[DailyBar]:
    start = date(2026, 1, 1)
    values: list[DailyBar] = []
    for index in range(sessions):
        open_price = 100 + index * daily_step
        values.append(
            DailyBar(
                session=(start + timedelta(days=index)).isoformat(),
                open=open_price,
                high=open_price * 1.01,
                low=open_price * 0.99,
                close=open_price + daily_step / 2,
                volume=1_000_000,
            )
        )
    return values


def _signal(symbol: str, session: str, *, notional: float = 10) -> BacktestSignal:
    return BacktestSignal(
        symbol=symbol,
        signal_session=session,
        horizon_trading_days=5,
        opportunity_score=85,
        risk_level=RiskLevel.LOW,
        notional_usd=notional,
    )


class UnlimitedFundingPortfolioTests(unittest.TestCase):
    def test_one_cohort_matches_trade_and_equal_dollar_spy_outcomes(self) -> None:
        stock = _bars(daily_step=2)
        spy = _bars(daily_step=0.5)
        simulated = simulate_close_signals(
            signals=[_signal("AAPL", stock[0].session)],
            bars_by_symbol={"AAPL": stock},
            spy_bars=spy,
            round_trip_cost_bps=10,
        )

        metrics = summarize_unlimited_funding_portfolio(
            simulated.trades,
            bars_by_symbol={"AAPL": stock},
            spy_bars=spy,
        )
        trade = simulated.trades[0]
        stock_metrics = metrics["stock"]
        spy_metrics = metrics["spy"]

        self.assertEqual(
            metrics["capital_model"],
            "unlimited_external_funding_fixed_trade_notional",
        )
        self.assertEqual(metrics["analytics_version"], "unlimited-funded-cohorts-v1")
        self.assertEqual(metrics["status"], "complete")
        self.assertEqual(stock_metrics["contributed_usd"], 10)
        self.assertAlmostEqual(
            stock_metrics["return_on_contributed_capital"], trade.outcome.net_return
        )
        self.assertAlmostEqual(
            spy_metrics["return_on_contributed_capital"], trade.outcome.spy_return
        )
        self.assertAlmostEqual(
            stock_metrics["compounded_return"], trade.outcome.net_return
        )
        self.assertAlmostEqual(spy_metrics["compounded_return"], trade.outcome.spy_return)
        self.assertAlmostEqual(
            metrics["excess"]["compounded_active_return"],
            (1 + trade.outcome.net_return) / (1 + trade.outcome.spy_return) - 1,
        )
        self.assertEqual(metrics["exposure"]["peak_concurrent_lots"], 1)
        self.assertLessEqual(stock_metrics["maximum_drawdown"], 0)

    def test_overlapping_cohorts_report_exposure_and_turnover(self) -> None:
        aapl = _bars(daily_step=1)
        msft = _bars(daily_step=-0.25)
        spy = _bars(daily_step=0.2)
        simulated = simulate_close_signals(
            signals=[
                _signal("AAPL", aapl[0].session, notional=15),
                _signal("MSFT", msft[1].session, notional=5),
            ],
            bars_by_symbol={"AAPL": aapl, "MSFT": msft},
            spy_bars=spy,
            round_trip_cost_bps=0,
        )

        metrics = summarize_unlimited_funding_portfolio(
            simulated.trades,
            bars_by_symbol={"AAPL": aapl, "MSFT": msft},
            spy_bars=spy,
        )

        self.assertEqual(metrics["trades"], 2)
        self.assertEqual(metrics["stock"]["contributed_usd"], 20)
        self.assertEqual(metrics["exposure"]["peak_concurrent_lots"], 2)
        self.assertGreater(metrics["exposure"]["average_active_capital_usd"], 0)
        self.assertGreater(metrics["turnover"]["gross_traded_value_usd"], 20)

    def test_no_trades_has_explicit_empty_status(self) -> None:
        metrics = summarize_unlimited_funding_portfolio(
            (), bars_by_symbol={}, spy_bars=[]
        )

        self.assertEqual(metrics["status"], "no_trades")
        self.assertIsNone(metrics["stock"])
        self.assertIsNone(metrics["exposure"])


if __name__ == "__main__":
    unittest.main()
