"""Point-in-time feature and transparent pillar construction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Mapping, Sequence

from .domain import PillarValue, RiskLevel


@dataclass(frozen=True, slots=True)
class DailyBar:
    session: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if not self.session:
            raise ValueError("daily bar session is required")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("daily bar prices must be positive")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("daily bar low is inconsistent")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("daily bar high is inconsistent")
        if self.volume < 0:
            raise ValueError("daily bar volume cannot be negative")


@dataclass(frozen=True, slots=True)
class FundamentalInputs:
    as_of: str
    revenue_growth: float | None = None
    net_margin: float | None = None
    free_cash_flow_margin: float | None = None
    debt_to_equity: float | None = None
    price_to_earnings: float | None = None
    free_cash_flow_yield: float | None = None


@dataclass(frozen=True, slots=True)
class FeatureSet:
    as_of: str
    raw: Mapping[str, float | int | str | None]
    pillars: Mapping[str, PillarValue]
    risk_level: RiskLevel


def build_feature_set(
    *,
    as_of: str,
    bars: Sequence[DailyBar],
    spy_bars: Sequence[DailyBar],
    fundamentals: FundamentalInputs | None,
    news_sentiments: Sequence[float] = (),
    news_coverage_complete: bool = False,
) -> FeatureSet:
    """Build v0 features from data already filtered to ``as_of``.

    Callers own point-in-time selection. This function additionally rejects any
    bar or fundamental timestamp later than ``as_of`` as a lookahead safeguard.
    """

    stock = _validated_history(bars, as_of, "stock")
    spy = _validated_history(spy_bars, as_of, "SPY")
    if fundamentals and fundamentals.as_of > as_of:
        raise ValueError("fundamentals contain future information")
    if any(not -1 <= value <= 1 for value in news_sentiments):
        raise ValueError("news sentiment must be between -1 and 1")

    raw: dict[str, float | int | str | None] = {"as_of": as_of}
    pillars: dict[str, PillarValue] = {}

    momentum_values = _momentum_features(stock, spy)
    raw.update(momentum_values)
    momentum_scores = [
        _linear_score(momentum_values.get("relative_return_21"), -0.10, 0.10),
        _linear_score(momentum_values.get("relative_return_63"), -0.20, 0.20),
        _linear_score(momentum_values.get("relative_return_126"), -0.30, 0.30),
        _linear_score(momentum_values.get("price_vs_ma50"), -0.10, 0.10),
        _linear_score(momentum_values.get("price_vs_ma200"), -0.15, 0.15),
    ]
    pillars["momentum"] = _pillar(momentum_scores, as_of)

    quality_scores: list[float | None] = []
    valuation_scores: list[float | None] = []
    if fundamentals:
        raw.update(
            {
                "revenue_growth": fundamentals.revenue_growth,
                "net_margin": fundamentals.net_margin,
                "free_cash_flow_margin": fundamentals.free_cash_flow_margin,
                "debt_to_equity": fundamentals.debt_to_equity,
                "price_to_earnings": fundamentals.price_to_earnings,
                "free_cash_flow_yield": fundamentals.free_cash_flow_yield,
            }
        )
        quality_scores = [
            _linear_score(fundamentals.revenue_growth, -0.10, 0.30),
            _linear_score(fundamentals.net_margin, -0.05, 0.25),
            _linear_score(fundamentals.free_cash_flow_margin, -0.05, 0.20),
            _linear_score(fundamentals.debt_to_equity, 3.0, 0.0),
        ]
        valuation_scores = [
            _linear_score(
                fundamentals.price_to_earnings
                if fundamentals.price_to_earnings and fundamentals.price_to_earnings > 0
                else None,
                40.0,
                10.0,
            ),
            _linear_score(fundamentals.free_cash_flow_yield, -0.02, 0.08),
        ]
    pillars["quality"] = _pillar(
        quality_scores, fundamentals.as_of if fundamentals else as_of
    )
    pillars["valuation"] = _pillar(
        valuation_scores, fundamentals.as_of if fundamentals else as_of
    )

    if news_coverage_complete:
        average_sentiment = fmean(news_sentiments) if news_sentiments else 0.0
        news_score = _linear_score(average_sentiment, -0.5, 0.5)
        raw["news_article_count"] = len(news_sentiments)
        raw["news_average_sentiment"] = average_sentiment
        pillars["news"] = PillarValue(
            score=round(news_score, 2) if news_score is not None else None,
            source_count=len(news_sentiments),
            as_of=as_of,
        )
    else:
        raw["news_article_count"] = None
        raw["news_average_sentiment"] = None
        pillars["news"] = PillarValue(score=None, as_of=as_of)

    regime_values = _regime_features(spy)
    raw.update(regime_values)
    regime_scores = [
        _linear_score(regime_values.get("spy_return_63"), -0.15, 0.15),
        _linear_score(regime_values.get("spy_price_vs_ma50"), -0.08, 0.08),
        _linear_score(regime_values.get("spy_price_vs_ma200"), -0.12, 0.12),
    ]
    pillars["market_regime"] = _pillar(regime_scores, as_of)

    risk_values = _risk_features(stock)
    raw.update(risk_values)
    risk_scores = [
        _linear_score(risk_values.get("annualized_volatility_21"), 0.60, 0.10),
        _linear_score(risk_values.get("maximum_drawdown_63"), -0.30, 0.0),
        _linear_score(risk_values.get("average_dollar_volume_21"), 20_000_000, 100_000_000),
    ]
    pillars["risk_liquidity"] = _pillar(risk_scores, as_of)
    risk_level = _classify_risk(risk_values)

    return FeatureSet(
        as_of=as_of,
        raw=raw,
        pillars=pillars,
        risk_level=risk_level,
    )


def _momentum_features(
    bars: Sequence[DailyBar], spy_bars: Sequence[DailyBar]
) -> dict[str, float | None]:
    stock_by_session = {bar.session: bar for bar in bars}
    spy_by_session = {bar.session: bar for bar in spy_bars}
    sessions = sorted(set(stock_by_session) & set(spy_by_session))
    stock_closes = [stock_by_session[session].close for session in sessions]
    spy_closes = [spy_by_session[session].close for session in sessions]
    values: dict[str, float | None] = {}
    for period in (21, 63, 126):
        stock_return = _period_return(stock_closes, period)
        spy_return = _period_return(spy_closes, period)
        values[f"return_{period}"] = stock_return
        values[f"spy_return_{period}"] = spy_return
        values[f"relative_return_{period}"] = (
            stock_return - spy_return
            if stock_return is not None and spy_return is not None
            else None
        )
    values["price_vs_ma50"] = _price_vs_average(stock_closes, 50)
    values["price_vs_ma200"] = _price_vs_average(stock_closes, 200)
    return values


def _regime_features(bars: Sequence[DailyBar]) -> dict[str, float | None]:
    closes = [bar.close for bar in bars]
    return {
        "spy_return_63": _period_return(closes, 63),
        "spy_price_vs_ma50": _price_vs_average(closes, 50),
        "spy_price_vs_ma200": _price_vs_average(closes, 200),
    }


def _risk_features(bars: Sequence[DailyBar]) -> dict[str, float | None]:
    closes = [bar.close for bar in bars]
    recent = bars[-21:]
    daily_returns = [
        closes[index] / closes[index - 1] - 1.0
        for index in range(max(1, len(closes) - 21), len(closes))
    ]
    volatility = (
        pstdev(daily_returns) * math.sqrt(252) if len(daily_returns) >= 2 else None
    )
    average_dollar_volume = (
        fmean(bar.close * bar.volume for bar in recent) if recent else None
    )
    return {
        "annualized_volatility_21": volatility,
        "average_dollar_volume_21": average_dollar_volume,
        "maximum_drawdown_63": _maximum_drawdown(closes[-63:]),
    }


def _classify_risk(values: Mapping[str, float | None]) -> RiskLevel:
    volatility = values.get("annualized_volatility_21")
    drawdown = values.get("maximum_drawdown_63")
    liquidity = values.get("average_dollar_volume_21")
    if (
        (volatility is not None and volatility > 0.60)
        or (drawdown is not None and drawdown < -0.30)
        or (liquidity is not None and liquidity < 20_000_000)
    ):
        return RiskLevel.HIGH
    if (
        (volatility is not None and volatility > 0.40)
        or (drawdown is not None and drawdown < -0.20)
        or (liquidity is not None and liquidity < 50_000_000)
    ):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _validated_history(
    bars: Sequence[DailyBar], as_of: str, label: str
) -> tuple[DailyBar, ...]:
    ordered = tuple(sorted(bars, key=lambda bar: bar.session))
    if not ordered:
        raise ValueError(f"{label} history is required")
    if len({bar.session for bar in ordered}) != len(ordered):
        raise ValueError(f"{label} history contains duplicate sessions")
    if ordered[-1].session > as_of:
        raise ValueError(f"{label} history contains future data")
    return ordered


def _period_return(closes: Sequence[float], sessions: int) -> float | None:
    if len(closes) <= sessions:
        return None
    return closes[-1] / closes[-(sessions + 1)] - 1.0


def _price_vs_average(closes: Sequence[float], sessions: int) -> float | None:
    if len(closes) < sessions:
        return None
    average = fmean(closes[-sessions:])
    return closes[-1] / average - 1.0


def _maximum_drawdown(closes: Sequence[float]) -> float | None:
    if not closes:
        return None
    peak = closes[0]
    drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = min(drawdown, close / peak - 1.0)
    return drawdown


def _pillar(values: Sequence[float | None], as_of: str) -> PillarValue:
    available = [value for value in values if value is not None]
    return PillarValue(
        score=round(fmean(available), 2) if available else None,
        source_count=len(available),
        as_of=as_of,
    )


def _linear_score(value: float | None, bad: float, good: float) -> float | None:
    if value is None:
        return None
    if bad == good:
        raise ValueError("score bounds cannot be equal")
    normalized = (value - bad) / (good - bad)
    return max(0.0, min(100.0, normalized * 100.0))
