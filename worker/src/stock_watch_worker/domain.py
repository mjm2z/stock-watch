"""Dependency-free domain types shared by scanners and backtests."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SignalDecision(StrEnum):
    QUALIFIED = "qualified"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PillarValue:
    """A normalized, point-in-time pillar value.

    ``score`` is on a 0-100 scale. An unavailable value is deliberately
    represented by ``None`` so missing data cannot silently become neutral.
    """

    score: float | None
    source_count: int = 0
    as_of: str | None = None

    def __post_init__(self) -> None:
        if self.score is not None and not 0 <= self.score <= 100:
            raise ValueError("pillar score must be between 0 and 100")
        if self.source_count < 0:
            raise ValueError("source_count cannot be negative")


@dataclass(frozen=True, slots=True)
class ScoreRequest:
    ticker: str
    pillars: Mapping[str, PillarValue]
    risk_level: RiskLevel
    vetoes: tuple[str, ...] = field(default_factory=tuple)
    in_universe: bool = True

    def __post_init__(self) -> None:
        normalized = self.ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker is required")
        object.__setattr__(self, "ticker", normalized)


@dataclass(frozen=True, slots=True)
class PillarContribution:
    name: str
    weight: float
    available: bool
    score: float | None
    weighted_points: float


@dataclass(frozen=True, slots=True)
class ScoreResult:
    ticker: str
    opportunity_score: float
    data_completeness: float
    risk_level: RiskLevel
    decision: SignalDecision
    reasons: tuple[str, ...]
    contributions: tuple[PillarContribution, ...]
