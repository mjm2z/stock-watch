"""Deterministic, cost-aware simulation for close-generated signals."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from .domain import RiskLevel
from .features import DailyBar
from .outcomes import SignalOutcome, OutcomeSummary, calculate_outcome, summarize_outcomes


SUPPORTED_HORIZONS = frozenset({5, 21, 63, 105})


@dataclass(frozen=True, slots=True)
class BacktestSignal:
    symbol: str
    signal_session: str
    horizon_trading_days: int
    opportunity_score: float
    risk_level: RiskLevel
    notional_usd: float = 10.0

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        object.__setattr__(self, "symbol", symbol)
        if not self.signal_session:
            raise ValueError("signal_session is required")
        if self.horizon_trading_days not in SUPPORTED_HORIZONS:
            raise ValueError("unsupported trading-day horizon")
        if not 0 <= self.opportunity_score <= 100:
            raise ValueError("opportunity_score must be between 0 and 100")
        if self.notional_usd <= 0:
            raise ValueError("notional_usd must be positive")


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    signal: BacktestSignal
    entry_session: str
    exit_session: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl_usd: float
    outcome: SignalOutcome


@dataclass(frozen=True, slots=True)
class RejectedSignal:
    signal: BacktestSignal
    reason: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: tuple[SimulatedTrade, ...]
    rejected: tuple[RejectedSignal, ...]
    summary: OutcomeSummary | None


@dataclass(frozen=True, slots=True)
class WalkForwardSplit:
    index: int
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    test_start: str
    test_end: str


def simulate_close_signals(
    *,
    signals: Sequence[BacktestSignal],
    bars_by_symbol: Mapping[str, Sequence[DailyBar]],
    spy_bars: Sequence[DailyBar],
    round_trip_cost_bps: float = 10.0,
    maximum_open_notional_per_symbol_usd: float = 30.0,
) -> BacktestResult:
    """Simulate signals without same-close fills or benchmark-window drift.

    The entry is the next available stock session's open. The entry session is
    day one of the holding period, and the exit uses that period's final close.
    SPY must have bars on both boundary sessions or the signal is rejected.
    """

    if round_trip_cost_bps < 0:
        raise ValueError("round_trip_cost_bps cannot be negative")
    if (
        maximum_open_notional_per_symbol_usd <= 0
        or not math.isfinite(maximum_open_notional_per_symbol_usd)
    ):
        raise ValueError("maximum open notional per symbol must be finite and positive")
    normalized_bars = {
        symbol.strip().upper(): _validated_bars(values, symbol)
        for symbol, values in bars_by_symbol.items()
    }
    benchmark = _validated_bars(spy_bars, "SPY")
    spy_by_session = {bar.session: bar for bar in benchmark}
    active_until: dict[tuple[str, int], str] = {}
    active_notional: dict[str, list[tuple[str, float]]] = {}
    trades: list[SimulatedTrade] = []
    rejected: list[RejectedSignal] = []

    ordered_signals = sorted(
        signals,
        key=lambda signal: (
            signal.signal_session,
            signal.symbol,
            signal.horizon_trading_days,
        ),
    )
    for signal in ordered_signals:
        key = (signal.symbol, signal.horizon_trading_days)
        previous_exit = active_until.get(key)
        if previous_exit is not None and signal.signal_session < previous_exit:
            rejected.append(RejectedSignal(signal, "duplicate_open_lot"))
            continue

        symbol_bars = normalized_bars.get(signal.symbol)
        if symbol_bars is None:
            rejected.append(RejectedSignal(signal, "missing_symbol_history"))
            continue
        entry_index = _first_session_after(symbol_bars, signal.signal_session)
        if entry_index is None:
            rejected.append(RejectedSignal(signal, "missing_next_session"))
            continue
        exit_index = entry_index + signal.horizon_trading_days - 1
        if exit_index >= len(symbol_bars):
            rejected.append(RejectedSignal(signal, "insufficient_future_history"))
            continue

        window = symbol_bars[entry_index : exit_index + 1]
        entry_bar = window[0]
        exit_bar = window[-1]
        spy_entry = spy_by_session.get(entry_bar.session)
        spy_exit = spy_by_session.get(exit_bar.session)
        if spy_entry is None or spy_exit is None:
            rejected.append(RejectedSignal(signal, "missing_benchmark_boundary"))
            continue

        active_symbol_lots = [
            value
            for value in active_notional.get(signal.symbol, [])
            if value[0] >= entry_bar.session
        ]
        active_notional[signal.symbol] = active_symbol_lots
        if (
            sum(value[1] for value in active_symbol_lots) + signal.notional_usd
            > maximum_open_notional_per_symbol_usd
        ):
            rejected.append(RejectedSignal(signal, "ticker_notional_limit"))
            continue

        outcome = calculate_outcome(
            entry_price=entry_bar.open,
            terminal_price=exit_bar.close,
            observed_highs=[bar.high for bar in window],
            observed_lows=[bar.low for bar in window],
            spy_entry_price=spy_entry.open,
            spy_terminal_price=spy_exit.close,
            round_trip_cost_bps=round_trip_cost_bps,
        )
        quantity = signal.notional_usd / entry_bar.open
        trades.append(
            SimulatedTrade(
                signal=signal,
                entry_session=entry_bar.session,
                exit_session=exit_bar.session,
                entry_price=entry_bar.open,
                exit_price=exit_bar.close,
                quantity=quantity,
                pnl_usd=signal.notional_usd * outcome.net_return,
                outcome=outcome,
            )
        )
        active_until[key] = exit_bar.session
        active_notional[signal.symbol].append((exit_bar.session, signal.notional_usd))

    summary = summarize_outcomes(trade.outcome for trade in trades) if trades else None
    return BacktestResult(tuple(trades), tuple(rejected), summary)


def make_walk_forward_splits(
    sessions: Sequence[str],
    *,
    train_sessions: int,
    validation_sessions: int,
    test_sessions: int,
    step_sessions: int | None = None,
    expanding: bool = True,
) -> tuple[WalkForwardSplit, ...]:
    """Create chronological train/validation/test ranges without random leakage."""

    if min(train_sessions, validation_sessions, test_sessions) <= 0:
        raise ValueError("split window sizes must be positive")
    step = test_sessions if step_sessions is None else step_sessions
    if step <= 0:
        raise ValueError("step_sessions must be positive")
    ordered = tuple(sorted(sessions))
    if len(set(ordered)) != len(ordered):
        raise ValueError("sessions contain duplicates")

    splits: list[WalkForwardSplit] = []
    origin = train_sessions
    while origin + validation_sessions + test_sessions <= len(ordered):
        train_start_index = 0 if expanding else origin - train_sessions
        validation_start = origin
        test_start = validation_start + validation_sessions
        splits.append(
            WalkForwardSplit(
                index=len(splits),
                train_start=ordered[train_start_index],
                train_end=ordered[origin - 1],
                validation_start=ordered[validation_start],
                validation_end=ordered[test_start - 1],
                test_start=ordered[test_start],
                test_end=ordered[test_start + test_sessions - 1],
            )
        )
        origin += step
    return tuple(splits)


def _validated_bars(bars: Sequence[DailyBar], label: str) -> tuple[DailyBar, ...]:
    ordered = tuple(sorted(bars, key=lambda bar: bar.session))
    if len({bar.session for bar in ordered}) != len(ordered):
        raise ValueError(f"{label} bars contain duplicate sessions")
    return ordered


def _first_session_after(bars: Sequence[DailyBar], session: str) -> int | None:
    for index, bar in enumerate(bars):
        if bar.session > session:
            return index
    return None
