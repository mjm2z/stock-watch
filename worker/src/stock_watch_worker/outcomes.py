"""Pure outcome calculations shared by forward tracking and backtests."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class SignalOutcome:
    entry_price: float
    terminal_price: float
    gross_return: float
    modeled_cost_return: float
    net_return: float
    terminal_positive: bool
    terminal_at_least_5: bool
    terminal_at_least_10: bool
    touched_5: bool
    touched_10: bool
    spy_return: float
    excess_return: float
    beat_spy: bool
    maximum_favorable_excursion: float
    maximum_adverse_excursion: float


@dataclass(frozen=True, slots=True)
class OutcomeSummary:
    observations: int
    positive_rate: float
    terminal_5_rate: float
    terminal_10_rate: float
    touched_5_rate: float
    touched_10_rate: float
    beat_spy_rate: float
    average_net_return: float
    average_spy_return: float
    average_excess_return: float
    average_maximum_favorable_excursion: float
    average_maximum_adverse_excursion: float


def calculate_outcome(
    *,
    entry_price: float,
    terminal_price: float,
    observed_highs: Sequence[float],
    observed_lows: Sequence[float],
    spy_entry_price: float,
    spy_terminal_price: float,
    round_trip_cost_bps: float = 10.0,
    spy_round_trip_cost_bps: float | None = None,
) -> SignalOutcome:
    """Measure an outcome using identical stock and SPY observation windows.

    Returns are decimal fractions: ``0.05`` means five percent. Threshold and
    positive labels use net terminal return after modeled round-trip costs.
    Touch labels and excursions describe observed prices before costs.
    """

    _require_positive("entry_price", entry_price)
    _require_positive("terminal_price", terminal_price)
    _require_positive("spy_entry_price", spy_entry_price)
    _require_positive("spy_terminal_price", spy_terminal_price)
    if not observed_highs or not observed_lows:
        raise ValueError("observed highs and lows are required")
    if len(observed_highs) != len(observed_lows):
        raise ValueError("observed highs and lows must have equal length")
    if any(value <= 0 for value in (*observed_highs, *observed_lows)):
        raise ValueError("observed prices must be positive")
    if round_trip_cost_bps < 0:
        raise ValueError("round_trip_cost_bps cannot be negative")

    benchmark_cost_bps = (
        round_trip_cost_bps
        if spy_round_trip_cost_bps is None
        else spy_round_trip_cost_bps
    )
    if benchmark_cost_bps < 0:
        raise ValueError("spy_round_trip_cost_bps cannot be negative")

    gross_return = terminal_price / entry_price - 1.0
    modeled_cost_return = round_trip_cost_bps / 10_000.0
    net_return = gross_return - modeled_cost_return

    spy_gross_return = spy_terminal_price / spy_entry_price - 1.0
    spy_return = spy_gross_return - benchmark_cost_bps / 10_000.0
    excess_return = net_return - spy_return

    maximum_favorable_excursion = max(observed_highs) / entry_price - 1.0
    maximum_adverse_excursion = min(observed_lows) / entry_price - 1.0

    return SignalOutcome(
        entry_price=entry_price,
        terminal_price=terminal_price,
        gross_return=gross_return,
        modeled_cost_return=modeled_cost_return,
        net_return=net_return,
        terminal_positive=net_return > 0,
        terminal_at_least_5=net_return >= 0.05,
        terminal_at_least_10=net_return >= 0.10,
        touched_5=maximum_favorable_excursion >= 0.05,
        touched_10=maximum_favorable_excursion >= 0.10,
        spy_return=spy_return,
        excess_return=excess_return,
        beat_spy=excess_return > 0,
        maximum_favorable_excursion=maximum_favorable_excursion,
        maximum_adverse_excursion=maximum_adverse_excursion,
    )


def summarize_outcomes(outcomes: Iterable[SignalOutcome]) -> OutcomeSummary:
    values = tuple(outcomes)
    if not values:
        raise ValueError("at least one outcome is required")

    return OutcomeSummary(
        observations=len(values),
        positive_rate=_rate(outcome.terminal_positive for outcome in values),
        terminal_5_rate=_rate(outcome.terminal_at_least_5 for outcome in values),
        terminal_10_rate=_rate(outcome.terminal_at_least_10 for outcome in values),
        touched_5_rate=_rate(outcome.touched_5 for outcome in values),
        touched_10_rate=_rate(outcome.touched_10 for outcome in values),
        beat_spy_rate=_rate(outcome.beat_spy for outcome in values),
        average_net_return=fmean(outcome.net_return for outcome in values),
        average_spy_return=fmean(outcome.spy_return for outcome in values),
        average_excess_return=fmean(outcome.excess_return for outcome in values),
        average_maximum_favorable_excursion=fmean(
            outcome.maximum_favorable_excursion for outcome in values
        ),
        average_maximum_adverse_excursion=fmean(
            outcome.maximum_adverse_excursion for outcome in values
        ),
    )


def _rate(values: Iterable[bool]) -> float:
    observations = tuple(values)
    return sum(observations) / len(observations)


def _require_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
