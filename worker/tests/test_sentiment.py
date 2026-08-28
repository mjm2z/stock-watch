from __future__ import annotations

import unittest

from stock_watch_worker.sentiment import calculate_news_sentiment


class NewsSentimentTests(unittest.TestCase):
    def test_positive_negative_and_neutral_language(self) -> None:
        self.assertGreater(
            calculate_news_sentiment("Company beats estimates and raises outlook"), 0
        )
        self.assertLess(
            calculate_news_sentiment("Company misses estimates after weak quarter"), 0
        )
        self.assertEqual(calculate_news_sentiment("Company schedules annual meeting"), 0)

    def test_headline_is_weighted_and_negation_flips_term(self) -> None:
        self.assertLess(calculate_news_sentiment("Results did not beat estimates"), 0)
        self.assertGreater(
            calculate_news_sentiment("Profit growth", "Analyst warns of risk"), 0
        )

    def test_score_is_bounded(self) -> None:
        value = " ".join(["beat", "growth", "profit", "upgrade"] * 20)
        self.assertEqual(calculate_news_sentiment(value), 1.0)


if __name__ == "__main__":
    unittest.main()
