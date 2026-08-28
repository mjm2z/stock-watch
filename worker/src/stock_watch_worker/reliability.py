"""Uncertainty estimates for out-of-sample binary investment outcomes."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

from .outcomes import SignalOutcome


WILSON_95_Z = 1.959963984540054


@dataclass(frozen=True, slots=True)
class BinomialReliability:
    successes: int
    observations: int
    estimate: float
    lower_95: float
    upper_95: float


def wilson_interval(
    successes: int,
    observations: int,
    *,
    z: float = WILSON_95_Z,
) -> tuple[float, float]:
    """Return a Wilson score interval without unstable normal edge behavior."""

    if observations < 1:
        raise ValueError("observations must be positive")
    if successes < 0 or successes > observations:
        raise ValueError("successes must be between zero and observations")
    if z <= 0 or not math.isfinite(z):
        raise ValueError("z must be finite and positive")
    proportion = successes / observations
    z_squared = z * z
    denominator = 1 + z_squared / observations
    center = (proportion + z_squared / (2 * observations)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / observations
            + z_squared / (4 * observations * observations)
        )
        / denominator
    )
    lower = 0.0 if successes == 0 else max(0.0, center - margin)
    upper = 1.0 if successes == observations else min(1.0, center + margin)
    return lower, upper


def summarize_reliability(
    outcomes: Iterable[SignalOutcome],
    *,
    minimum_observations: int = 30,
) -> Mapping[str, object]:
    """Describe empirical hit rates while making sparse cohorts explicit.

    These are confidence intervals around observed out-of-sample frequencies,
    not per-signal probability forecasts.
    """

    if minimum_observations < 1:
        raise ValueError("minimum_observations must be positive")
    values = tuple(outcomes)
    observations = len(values)
    status = (
        "no_observations"
        if observations == 0
        else "reportable"
        if observations >= minimum_observations
        else "underpowered"
    )
    return {
        "observations": observations,
        "minimum_observations": minimum_observations,
        "status": status,
        "confidence_level": 0.95,
        "probability_forecast": False,
        "positive_return": _estimate(
            sum(outcome.terminal_positive for outcome in values), observations
        ),
        "beat_spy": _estimate(
            sum(outcome.beat_spy for outcome in values), observations
        ),
        "terminal_at_least_5": _estimate(
            sum(outcome.terminal_at_least_5 for outcome in values), observations
        ),
        "terminal_at_least_10": _estimate(
            sum(outcome.terminal_at_least_10 for outcome in values), observations
        ),
    }


def _estimate(successes: int, observations: int) -> Mapping[str, object] | None:
    if observations == 0:
        return None
    lower, upper = wilson_interval(successes, observations)
    return asdict(
        BinomialReliability(
            successes=successes,
            observations=observations,
            estimate=successes / observations,
            lower_95=lower,
            upper_95=upper,
        )
    )
