from __future__ import annotations

import unittest

from stock_watch_worker.outcomes import calculate_outcome, summarize_outcomes


class OutcomeTests(unittest.TestCase):
    def test_tracks_terminal_touch_and_benchmark_results_separately(self) -> None:
        outcome = calculate_outcome(
            entry_price=100,
            terminal_price=106,
            observed_highs=[102, 111, 108, 106],
            observed_lows=[98, 101, 103, 104],
            spy_entry_price=500,
            spy_terminal_price=520,
            round_trip_cost_bps=10,
        )

        self.assertAlmostEqual(outcome.gross_return, 0.06)
        self.assertAlmostEqual(outcome.net_return, 0.059)
        self.assertTrue(outcome.terminal_positive)
        self.assertTrue(outcome.terminal_at_least_5)
        self.assertFalse(outcome.terminal_at_least_10)
        self.assertTrue(outcome.touched_10)
        self.assertTrue(outcome.beat_spy)
        self.assertAlmostEqual(outcome.maximum_favorable_excursion, 0.11)
        self.assertAlmostEqual(outcome.maximum_adverse_excursion, -0.02)

    def test_marks_positive_stock_as_relative_failure_when_spy_does_better(self) -> None:
        outcome = calculate_outcome(
            entry_price=100,
            terminal_price=103,
            observed_highs=[104],
            observed_lows=[99],
            spy_entry_price=500,
            spy_terminal_price=530,
        )

        self.assertTrue(outcome.terminal_positive)
        self.assertFalse(outcome.beat_spy)
        self.assertLess(outcome.excess_return, 0)

    def test_net_threshold_includes_modeled_costs(self) -> None:
        outcome = calculate_outcome(
            entry_price=100,
            terminal_price=105,
            observed_highs=[105],
            observed_lows=[100],
            spy_entry_price=500,
            spy_terminal_price=500,
            round_trip_cost_bps=10,
        )

        self.assertAlmostEqual(outcome.gross_return, 0.05)
        self.assertAlmostEqual(outcome.net_return, 0.049)
        self.assertFalse(outcome.terminal_at_least_5)
        self.assertTrue(outcome.touched_5)

    def test_requires_aligned_valid_price_observations(self) -> None:
        with self.assertRaisesRegex(ValueError, "equal length"):
            calculate_outcome(
                entry_price=100,
                terminal_price=101,
                observed_highs=[101, 102],
                observed_lows=[99],
                spy_entry_price=500,
                spy_terminal_price=501,
            )

    def test_equal_weight_summary(self) -> None:
        winner = calculate_outcome(
            entry_price=100,
            terminal_price=110,
            observed_highs=[111],
            observed_lows=[99],
            spy_entry_price=500,
            spy_terminal_price=510,
            round_trip_cost_bps=0,
        )
        loser = calculate_outcome(
            entry_price=100,
            terminal_price=90,
            observed_highs=[101],
            observed_lows=[88],
            spy_entry_price=500,
            spy_terminal_price=505,
            round_trip_cost_bps=0,
        )

        summary = summarize_outcomes([winner, loser])
        self.assertEqual(summary.observations, 2)
        self.assertEqual(summary.positive_rate, 0.5)
        self.assertEqual(summary.beat_spy_rate, 0.5)
        self.assertAlmostEqual(summary.average_net_return, 0.0)


if __name__ == "__main__":
    unittest.main()
