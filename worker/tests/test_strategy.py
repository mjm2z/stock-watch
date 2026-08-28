from __future__ import annotations

import unittest

from stock_watch_worker.domain import (
    PillarValue,
    RiskLevel,
    ScoreRequest,
    SignalDecision,
)
from stock_watch_worker.strategy import calculate_notional, calculate_score


def complete_pillars(score: float) -> dict[str, PillarValue]:
    return {
        "momentum": PillarValue(score),
        "quality": PillarValue(score),
        "valuation": PillarValue(score),
        "news": PillarValue(score),
        "market_regime": PillarValue(score),
        "risk_liquidity": PillarValue(score),
    }


class ScoreTests(unittest.TestCase):
    def test_qualifies_complete_low_risk_signal(self) -> None:
        result = calculate_score(
            ScoreRequest("aapl", complete_pillars(82), RiskLevel.LOW)
        )

        self.assertEqual(result.ticker, "AAPL")
        self.assertEqual(result.opportunity_score, 82)
        self.assertEqual(result.data_completeness, 100)
        self.assertEqual(result.decision, SignalDecision.QUALIFIED)
        self.assertEqual(result.reasons, ())

    def test_rejects_below_score_threshold(self) -> None:
        result = calculate_score(
            ScoreRequest("MSFT", complete_pillars(74.99), RiskLevel.LOW)
        )

        self.assertEqual(result.decision, SignalDecision.REJECTED)
        self.assertIn("score_below_threshold", result.reasons)

    def test_rejects_insufficient_weighted_completeness(self) -> None:
        pillars = complete_pillars(90)
        pillars["momentum"] = PillarValue(None)
        result = calculate_score(ScoreRequest("NVDA", pillars, RiskLevel.LOW))

        self.assertEqual(result.data_completeness, 75)
        self.assertEqual(result.decision, SignalDecision.REJECTED)
        self.assertIn("insufficient_data", result.reasons)

    def test_rejects_high_risk_signal(self) -> None:
        result = calculate_score(
            ScoreRequest("META", complete_pillars(95), RiskLevel.HIGH)
        )

        self.assertEqual(result.decision, SignalDecision.REJECTED)
        self.assertIn("risk_not_allowed", result.reasons)

    def test_rejects_veto_and_out_of_universe(self) -> None:
        result = calculate_score(
            ScoreRequest(
                "XYZ",
                complete_pillars(95),
                RiskLevel.LOW,
                vetoes=("stale_quote",),
                in_universe=False,
            )
        )

        self.assertEqual(result.decision, SignalDecision.REJECTED)
        self.assertIn("not_in_universe", result.reasons)
        self.assertIn("veto:stale_quote", result.reasons)

    def test_available_pillars_are_weighted_without_imputing_missing_values(self) -> None:
        pillars = complete_pillars(80)
        pillars["market_regime"] = PillarValue(None)
        pillars["risk_liquidity"] = PillarValue(100)
        result = calculate_score(ScoreRequest("JPM", pillars, RiskLevel.LOW))

        self.assertAlmostEqual(result.data_completeness, 90)
        expected = ((0.75 * 80) + (0.15 * 100)) / 0.90
        self.assertAlmostEqual(result.opportunity_score, round(expected, 2))


class SizingTests(unittest.TestCase):
    def test_low_risk_score_bands(self) -> None:
        cases = (
            (75, 7.5),
            (79.99, 7.5),
            (80, 10.0),
            (88, 12.5),
            (94, 15.0),
            (100, 15.0),
        )
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(calculate_notional(score, RiskLevel.LOW), expected)

    def test_medium_risk_adjustment_rounds_to_half_dollar(self) -> None:
        self.assertEqual(calculate_notional(80, RiskLevel.MEDIUM), 8.5)
        self.assertEqual(calculate_notional(88, RiskLevel.MEDIUM), 10.5)
        self.assertEqual(calculate_notional(94, RiskLevel.MEDIUM), 13.0)

    def test_rejects_unqualified_or_high_risk_sizing(self) -> None:
        with self.assertRaises(ValueError):
            calculate_notional(74.99, RiskLevel.LOW)
        with self.assertRaises(ValueError):
            calculate_notional(95, RiskLevel.HIGH)


if __name__ == "__main__":
    unittest.main()
