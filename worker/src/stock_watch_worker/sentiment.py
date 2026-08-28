"""Small deterministic news sentiment model for the zero-cost v0 strategy."""

from __future__ import annotations

import math
import re


MODEL_VERSION = "lexicon-v0"
TOKEN_PATTERN = re.compile(r"[a-z]+(?:'[a-z]+)?")
POSITIVE = frozenset(
    {
        "accelerate",
        "approval",
        "beat",
        "beats",
        "breakthrough",
        "growth",
        "improve",
        "improved",
        "outperform",
        "profit",
        "profitable",
        "raise",
        "raised",
        "record",
        "surge",
        "upgrade",
        "upside",
    }
)
NEGATIVE = frozenset(
    {
        "bankruptcy",
        "cut",
        "cuts",
        "decline",
        "downgrade",
        "fraud",
        "investigation",
        "loss",
        "miss",
        "misses",
        "recall",
        "risk",
        "slump",
        "warning",
        "weak",
    }
)
NEGATIONS = frozenset({"not", "no", "never", "without"})


def calculate_news_sentiment(headline: str, summary: str | None = None) -> float:
    """Return a transparent -1 to +1 lexicon score.

    Headlines count twice. A negation immediately before a sentiment term flips
    that term, keeping the model deterministic and auditable without an LLM.
    """

    headline_score, headline_hits = _score_text(headline)
    summary_score, summary_hits = _score_text(summary or "")
    weighted_score = headline_score * 2 + summary_score
    weighted_hits = headline_hits * 2 + summary_hits
    if weighted_hits == 0:
        return 0.0
    normalized = weighted_score / math.sqrt(weighted_hits)
    return round(max(-1.0, min(1.0, normalized)), 4)


def _score_text(value: str) -> tuple[int, int]:
    tokens = TOKEN_PATTERN.findall(value.lower())
    score = 0
    hits = 0
    for index, token in enumerate(tokens):
        direction = 1 if token in POSITIVE else -1 if token in NEGATIVE else 0
        if direction == 0:
            continue
        if index > 0 and tokens[index - 1] in NEGATIONS:
            direction *= -1
        score += direction
        hits += 1
    return score, hits
