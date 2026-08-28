from __future__ import annotations

import unittest

from stock_watch_worker.outcomes import calculate_outcome
from stock_watch_worker.reliability import summarize_reliability, wilson_interval


def _outcome(*, stock_return: float, spy_return: float = 0.0):
    return calculate_outcome(
        entry_price=100,
        terminal_price=100 * (1 + stock_return),
        observed_highs=[100 * (1 + max(stock_return, 0))],
        observed_lows=[100 * (1 + min(stock_return, 0))],
        spy_entry_price=100,
        spy_terminal_price=100 * (1 + spy_return),
        round_trip_cost_bps=0,
    )


class ReliabilityTests(unittest.TestCase):
    def test_wilson_interval_is_bounded_at_rate_extremes(self) -> None:
        lower, upper = wilson_interval(0, 10)
        self.assertEqual(lower, 0)
        self.assertAlmostEqual(upper, 0.2775328)

        lower, upper = wilson_interval(10, 10)
        self.assertAlmostEqual(lower, 0.7224672)
        self.assertEqual(upper, 1)

    def test_reports_both_accepted_success_definitions_with_uncertainty(self) -> None:
        report = summarize_reliability(
            [
                _outcome(stock_return=0.06, spy_return=0.01),
                _outcome(stock_return=0.03, spy_return=0.04),
                _outcome(stock_return=-0.01, spy_return=-0.02),
                _outcome(stock_return=-0.02, spy_return=0.01),
            ],
            minimum_observations=4,
        )

        self.assertEqual(report["status"], "reportable")
        self.assertFalse(report["probability_forecast"])
        self.assertEqual(report["positive_return"]["successes"], 2)
        self.assertEqual(report["positive_return"]["estimate"], 0.5)
        self.assertEqual(report["beat_spy"]["successes"], 2)
        self.assertEqual(report["terminal_at_least_5"]["successes"], 1)

    def test_sparse_and_empty_cohorts_are_not_overstated(self) -> None:
        sparse = summarize_reliability(
            [_outcome(stock_return=0.02)], minimum_observations=30
        )
        empty = summarize_reliability([], minimum_observations=30)

        self.assertEqual(sparse["status"], "underpowered")
        self.assertEqual(empty["status"], "no_observations")
        self.assertIsNone(empty["positive_return"])

    def test_validates_counts_and_minimum(self) -> None:
        with self.assertRaisesRegex(ValueError, "between"):
            wilson_interval(2, 1)
        with self.assertRaisesRegex(ValueError, "positive"):
            summarize_reliability([], minimum_observations=0)


if __name__ == "__main__":
    unittest.main()
