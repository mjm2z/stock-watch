"""Unlimited-funding cohort analytics for completed backtest trades."""

from __future__ import annotations

import math
from statistics import fmean, pstdev
from typing import Any, Mapping, Sequence

from .backtest import SimulatedTrade
from .features import DailyBar


TRADING_SESSIONS_PER_YEAR = 252
PORTFOLIO_ANALYTICS_VERSION = "unlimited-funded-cohorts-v1"


def summarize_unlimited_funding_portfolio(
    trades: Sequence[SimulatedTrade],
    *,
    bars_by_symbol: Mapping[str, Sequence[DailyBar]],
    spy_bars: Sequence[DailyBar],
) -> Mapping[str, Any]:
    """Summarize fixed-size cohorts without imposing an aggregate cash cap.

    Every accepted lot receives its configured external contribution. Daily
    performance is the capital-weighted return of active cohorts; sessions with
    no positions contribute zero. SPY receives the same dollars on the same
    entry/exit sessions.
    """

    values = tuple(trades)
    if not values:
        return {
            "analytics_version": PORTFOLIO_ANALYTICS_VERSION,
            "capital_model": "unlimited_external_funding_fixed_trade_notional",
            "status": "no_trades",
            "stock": None,
            "spy": None,
            "excess": None,
            "exposure": None,
            "turnover": None,
        }

    normalized_bars = {
        symbol.strip().upper(): {bar.session: bar for bar in symbol_bars}
        for symbol, symbol_bars in bars_by_symbol.items()
    }
    benchmark = {bar.session: bar for bar in spy_bars}
    benchmark_quantities: dict[int, float] = {}
    for index, trade in enumerate(values):
        entry_bar = benchmark.get(trade.entry_session)
        if entry_bar is None:
            raise ValueError(
                f"portfolio analytics are missing SPY entry bar {trade.entry_session}"
            )
        benchmark_quantities[index] = trade.signal.notional_usd / entry_bar.open

        if trade.signal.symbol not in normalized_bars:
            raise ValueError(
                f"portfolio analytics are missing bars for {trade.signal.symbol}"
            )
    sessions = tuple(
        bar.session
        for bar in spy_bars
        if min(trade.entry_session for trade in values)
        <= bar.session
        <= max(trade.exit_session for trade in values)
    )
    if not sessions:
        raise ValueError("portfolio analytics have no benchmark sessions")

    stock_states: dict[int, float] = {}
    spy_states: dict[int, float] = {}
    stock_returns: list[float] = []
    spy_returns: list[float] = []
    exposures: list[float] = []
    concurrent: list[int] = []
    for session in sessions:
        stock_start = stock_end = spy_start = spy_end = 0.0
        active = 0
        for index, trade in enumerate(values):
            if not trade.entry_session <= session <= trade.exit_session:
                continue
            active += 1
            trade_start = (
                trade.signal.notional_usd
                if session == trade.entry_session
                else stock_states[index]
            )
            benchmark_start = (
                trade.signal.notional_usd
                if session == trade.entry_session
                else spy_states[index]
            )
            if session == trade.exit_session:
                trade_end = trade.signal.notional_usd * (1 + trade.outcome.net_return)
                benchmark_end = trade.signal.notional_usd * (1 + trade.outcome.spy_return)
            else:
                stock_bar = normalized_bars.get(trade.signal.symbol, {}).get(session)
                trade_end = (
                    trade.quantity * stock_bar.close
                    if stock_bar is not None
                    else trade_start
                )
                benchmark_end = benchmark_quantities[index] * benchmark[session].close
            stock_states[index] = trade_end
            spy_states[index] = benchmark_end
            stock_start += trade_start
            stock_end += trade_end
            spy_start += benchmark_start
            spy_end += benchmark_end
        exposures.append(stock_start)
        concurrent.append(active)
        stock_returns.append(stock_end / stock_start - 1 if stock_start else 0.0)
        spy_returns.append(spy_end / spy_start - 1 if spy_start else 0.0)

    contributed = sum(trade.signal.notional_usd for trade in values)
    stock_ending = sum(
        trade.signal.notional_usd * (1 + trade.outcome.net_return)
        for trade in values
    )
    spy_ending = sum(
        trade.signal.notional_usd * (1 + trade.outcome.spy_return)
        for trade in values
    )
    stock_performance = _performance(stock_returns)
    spy_performance = _performance(spy_returns)
    active_performance = _performance(
        tuple(
            (1 + stock_return) / (1 + spy_return) - 1
            for stock_return, spy_return in zip(stock_returns, spy_returns, strict=True)
        )
    )
    active_exposures = [value for value in exposures if value > 0]
    average_exposure = fmean(exposures)
    gross_turnover = contributed + stock_ending
    return {
        "analytics_version": PORTFOLIO_ANALYTICS_VERSION,
        "capital_model": "unlimited_external_funding_fixed_trade_notional",
        "status": "complete",
        "trades": len(values),
        "sessions": len(sessions),
        "stock": {
            **stock_performance,
            "contributed_usd": contributed,
            "ending_cohort_value_usd": stock_ending,
            "pnl_usd": stock_ending - contributed,
            "return_on_contributed_capital": stock_ending / contributed - 1,
        },
        "spy": {
            **spy_performance,
            "contributed_usd": contributed,
            "ending_cohort_value_usd": spy_ending,
            "pnl_usd": spy_ending - contributed,
            "return_on_contributed_capital": spy_ending / contributed - 1,
        },
        "excess": {
            "pnl_usd": stock_ending - spy_ending,
            "return_on_contributed_capital": (
                stock_ending / contributed - spy_ending / contributed
            ),
            "compounded_active_return": active_performance["compounded_return"],
            "annualized_active_return": active_performance["annualized_return"],
        },
        "exposure": {
            "active_sessions": len(active_exposures),
            "inactive_sessions": len(sessions) - len(active_exposures),
            "active_session_rate": len(active_exposures) / len(sessions),
            "average_active_capital_usd": average_exposure,
            "peak_active_capital_usd": max(exposures),
            "average_concurrent_lots": fmean(concurrent),
            "peak_concurrent_lots": max(concurrent),
        },
        "turnover": {
            "entry_notional_usd": contributed,
            "exit_value_usd": stock_ending,
            "gross_traded_value_usd": gross_turnover,
            "gross_turnover_to_average_active_capital": (
                gross_turnover / average_exposure if average_exposure else None
            ),
        },
    }


def _performance(returns: Sequence[float]) -> Mapping[str, float | None]:
    compounded = math.prod(1 + value for value in returns) - 1
    annualized = (
        (1 + compounded) ** (TRADING_SESSIONS_PER_YEAR / len(returns)) - 1
        if compounded > -1
        else None
    )
    daily_volatility = pstdev(returns) if len(returns) > 1 else 0.0
    downside_deviation = math.sqrt(fmean(min(value, 0.0) ** 2 for value in returns))
    return {
        "compounded_return": compounded,
        "annualized_return": annualized,
        "annualized_volatility": daily_volatility * math.sqrt(TRADING_SESSIONS_PER_YEAR),
        "sharpe_ratio": (
            fmean(returns) / daily_volatility * math.sqrt(TRADING_SESSIONS_PER_YEAR)
            if daily_volatility > 0
            else None
        ),
        "sortino_ratio": (
            fmean(returns) / downside_deviation * math.sqrt(TRADING_SESSIONS_PER_YEAR)
            if downside_deviation > 0
            else None
        ),
        "maximum_drawdown": _maximum_drawdown(returns),
    }


def _maximum_drawdown(returns: Sequence[float]) -> float:
    value = peak = 1.0
    drawdown = 0.0
    for daily_return in returns:
        value *= 1 + daily_return
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    return drawdown
