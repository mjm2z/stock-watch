"""Versioned heuristic scoring and paper-notional sizing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Sequence

from .domain import (
    PillarContribution,
    RiskLevel,
    ScoreRequest,
    ScoreResult,
    SignalDecision,
)


DEFAULT_WEIGHTS: Mapping[str, float] = {
    "momentum": 0.25,
    "quality": 0.20,
    "valuation": 0.15,
    "news": 0.15,
    "market_regime": 0.10,
    "risk_liquidity": 0.15,
}


@dataclass(frozen=True, slots=True)
class QualificationPolicy:
    minimum_score: float = 75.0
    minimum_data_completeness: float = 80.0
    allowed_risk_levels: tuple[RiskLevel, ...] = (
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
    )


@dataclass(frozen=True, slots=True)
class SizingBand:
    minimum_score: float
    notional_usd: float


@dataclass(frozen=True, slots=True)
class SizingPolicy:
    minimum_notional_usd: float = 5.0
    maximum_notional_usd: float = 15.0
    medium_risk_multiplier: float = 0.85
    rounding_increment_usd: float = 0.50
    bands: tuple[SizingBand, ...] = (
        SizingBand(75.0, 7.50),
        SizingBand(80.0, 10.00),
        SizingBand(88.0, 12.50),
        SizingBand(94.0, 15.00),
    )


def calculate_score(
    request: ScoreRequest,
    *,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
    policy: QualificationPolicy = QualificationPolicy(),
) -> ScoreResult:
    """Calculate a transparent score without inventing missing information."""

    _validate_weights(weights)
    contributions: list[PillarContribution] = []
    available_weight = 0.0
    weighted_points = 0.0

    for name, weight in weights.items():
        value = request.pillars.get(name)
        available = value is not None and value.score is not None
        points = weight * value.score if available and value else 0.0
        if available:
            available_weight += weight
            weighted_points += points
        contributions.append(
            PillarContribution(
                name=name,
                weight=weight,
                available=available,
                score=value.score if value else None,
                weighted_points=round(points, 4),
            )
        )

    completeness = available_weight * 100.0
    score = weighted_points / available_weight if available_weight else 0.0
    score = round(score, 2)
    completeness = round(completeness, 2)

    reasons: list[str] = []
    if not request.in_universe:
        reasons.append("not_in_universe")
    if score < policy.minimum_score:
        reasons.append("score_below_threshold")
    if completeness < policy.minimum_data_completeness:
        reasons.append("insufficient_data")
    if request.risk_level not in policy.allowed_risk_levels:
        reasons.append("risk_not_allowed")
    reasons.extend(f"veto:{veto}" for veto in request.vetoes)

    decision = SignalDecision.REJECTED if reasons else SignalDecision.QUALIFIED
    return ScoreResult(
        ticker=request.ticker,
        opportunity_score=score,
        data_completeness=completeness,
        risk_level=request.risk_level,
        decision=decision,
        reasons=tuple(reasons),
        contributions=tuple(contributions),
    )


def calculate_notional(
    score: float,
    risk_level: RiskLevel,
    *,
    policy: SizingPolicy = SizingPolicy(),
) -> float:
    """Return the paper notional for an already-qualified signal."""

    if not 0 <= score <= 100:
        raise ValueError("score must be between 0 and 100")
    if risk_level is RiskLevel.HIGH:
        raise ValueError("high-risk signals are not eligible for sizing")

    applicable = [band for band in policy.bands if score >= band.minimum_score]
    if not applicable:
        raise ValueError("score is below the lowest sizing band")

    band = max(applicable, key=lambda item: item.minimum_score)
    notional = band.notional_usd
    if risk_level is RiskLevel.MEDIUM:
        notional *= policy.medium_risk_multiplier

    notional = min(
        policy.maximum_notional_usd,
        max(policy.minimum_notional_usd, notional),
    )
    return _round_to_increment(notional, policy.rounding_increment_usd)


def _validate_weights(weights: Mapping[str, float]) -> None:
    if not weights:
        raise ValueError("at least one pillar weight is required")
    if any(weight <= 0 for weight in weights.values()):
        raise ValueError("pillar weights must be positive")
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("pillar weights must sum to 1.0")


def _round_to_increment(value: float, increment: float) -> float:
    if increment <= 0:
        raise ValueError("rounding increment must be positive")
    value_decimal = Decimal(str(value))
    increment_decimal = Decimal(str(increment))
    units = (value_decimal / increment_decimal).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return float(units * increment_decimal)
