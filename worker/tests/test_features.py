from __future__ import annotations

import unittest
from datetime import date, timedelta

from stock_watch_worker.domain import RiskLevel
from stock_watch_worker.features import (
    DailyBar,
    FundamentalInputs,
    build_feature_set,
)


def _bars(
    *,
    sessions: int = 220,
    daily_return: float = 0.001,
    volume: float = 2_000_000,
) -> list[DailyBar]:
    values: list[DailyBar] = []
    close = 100.0
    start = date(2025, 1, 1)
    for index in range(sessions):
        close *= 1.0 + daily_return
        values.append(
            DailyBar(
                session=(start + timedelta(days=index)).isoformat(),
                open=close * 0.999,
                high=close * 1.003,
                low=close * 0.997,
                close=close,
                volume=volume,
            )
        )
    return values


class FeatureTests(unittest.TestCase):
    def test_builds_all_point_in_time_pillars_for_complete_data(self) -> None:
        stock = _bars(daily_return=0.002)
        spy = _bars(daily_return=0.0005)
        as_of = stock[-1].session
        fundamentals = FundamentalInputs(
            as_of=as_of,
            revenue_growth=0.20,
            net_margin=0.18,
            free_cash_flow_margin=0.15,
            debt_to_equity=0.5,
            price_to_earnings=18.0,
            free_cash_flow_yield=0.06,
        )

        result = build_feature_set(
            as_of=as_of,
            bars=stock,
            spy_bars=spy,
            fundamentals=fundamentals,
            news_sentiments=(0.2, 0.4),
            news_coverage_complete=True,
        )

        self.assertEqual(
            set(result.pillars),
            {"momentum", "quality", "valuation", "news", "market_regime", "risk_liquidity"},
        )
        self.assertTrue(all(value.score is not None for value in result.pillars.values()))
        self.assertGreater(result.pillars["momentum"].score or 0, 70)
        self.assertEqual(result.pillars["quality"].source_count, 4)
        self.assertEqual(result.pillars["valuation"].source_count, 2)
        self.assertEqual(result.pillars["news"].source_count, 2)
        self.assertEqual(result.risk_level, RiskLevel.LOW)
        self.assertGreater(result.raw["relative_return_63"] or 0, 0)

    def test_missing_sources_remain_unavailable_instead_of_neutral(self) -> None:
        bars = _bars()
        result = build_feature_set(
            as_of=bars[-1].session,
            bars=bars,
            spy_bars=bars,
            fundamentals=None,
            news_coverage_complete=False,
        )

        self.assertIsNone(result.pillars["quality"].score)
        self.assertIsNone(result.pillars["valuation"].score)
        self.assertIsNone(result.pillars["news"].score)
        self.assertIsNone(result.raw["news_article_count"])

    def test_low_liquidity_is_high_risk(self) -> None:
        bars = _bars(volume=1_000)
        result = build_feature_set(
            as_of=bars[-1].session,
            bars=bars,
            spy_bars=bars,
            fundamentals=None,
        )

        self.assertEqual(result.risk_level, RiskLevel.HIGH)

    def test_rejects_future_price_or_fundamental_information(self) -> None:
        bars = _bars(sessions=30)
        cutoff = bars[-2].session
        with self.assertRaisesRegex(ValueError, "future data"):
            build_feature_set(
                as_of=cutoff,
                bars=bars,
                spy_bars=bars[:-1],
                fundamentals=None,
            )

        with self.assertRaisesRegex(ValueError, "future information"):
            build_feature_set(
                as_of=bars[-1].session,
                bars=bars,
                spy_bars=bars,
                fundamentals=FundamentalInputs(as_of="2099-01-01"),
            )

    def test_rejects_duplicate_sessions_and_invalid_sentiment(self) -> None:
        bars = _bars(sessions=30)
        with self.assertRaisesRegex(ValueError, "duplicate sessions"):
            build_feature_set(
                as_of=bars[-1].session,
                bars=bars + [bars[-1]],
                spy_bars=bars,
                fundamentals=None,
            )
        with self.assertRaisesRegex(ValueError, "sentiment"):
            build_feature_set(
                as_of=bars[-1].session,
                bars=bars,
                spy_bars=bars,
                fundamentals=None,
                news_sentiments=(1.1,),
            )


if __name__ == "__main__":
    unittest.main()
