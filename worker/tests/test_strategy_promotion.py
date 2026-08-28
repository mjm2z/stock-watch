from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stock_watch_worker.config import load_strategy
from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations, register_strategy
from stock_watch_worker.strategy_promotion import promote_strategy_to_paper


STRATEGY_PATH = Path(__file__).resolve().parents[1] / "config" / "strategy-v0.json"
NOW = datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)


class StrategyPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        register_strategy(self.connection, load_strategy(STRATEGY_PATH))

    def tearDown(self) -> None:
        self.connection.close()

    def test_creates_new_immutable_paper_version_and_audit_event(self) -> None:
        result = promote_strategy_to_paper(
            self.connection,
            source_strategy_id="sp500-long-v0",
            paper_strategy_id="sp500-long-paper-v1",
            confirmation="sp500-long-paper-v1",
            now=NOW,
        )

        self.assertTrue(result.created)
        source = self.connection.execute(
            "SELECT status, promoted_at FROM strategy_versions WHERE id = 'sp500-long-v0'"
        ).fetchone()
        paper = self.connection.execute(
            "SELECT * FROM strategy_versions WHERE id = 'sp500-long-paper-v1'"
        ).fetchone()
        self.assertEqual(source["status"], "development")
        self.assertIsNone(source["promoted_at"])
        self.assertEqual(paper["status"], "paper")
        self.assertEqual(paper["promoted_at"], "2026-08-26T18:00:00Z")
        document = json.loads(paper["config_json"])
        self.assertEqual(document["id"], "sp500-long-paper-v1")
        self.assertEqual(document["status"], "paper")
        self.assertEqual(document["execution"]["mode"], "paper")
        self.assertEqual(document["sizing"]["maximum_notional_usd"], 15)
        self.assertEqual(
            document["sizing"]["maximum_open_notional_per_ticker_usd"], 30
        )
        audit = self.connection.execute(
            """
            SELECT payload_json FROM audit_events
            WHERE event_type = 'strategy_promoted_to_paper'
            """
        ).fetchone()
        payload = json.loads(audit["payload_json"])
        self.assertEqual(payload["source_strategy_id"], "sp500-long-v0")
        self.assertEqual(payload["paper_strategy_id"], "sp500-long-paper-v1")

    def test_identical_retry_is_idempotent(self) -> None:
        first = promote_strategy_to_paper(
            self.connection,
            source_strategy_id="sp500-long-v0",
            paper_strategy_id="sp500-long-paper-v1",
            confirmation="sp500-long-paper-v1",
            now=NOW,
        )
        second = promote_strategy_to_paper(
            self.connection,
            source_strategy_id="sp500-long-v0",
            paper_strategy_id="sp500-long-paper-v1",
            confirmation="sp500-long-paper-v1",
            now=datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.promoted_at, first.promoted_at)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'strategy_promoted_to_paper'"
            ).fetchone()[0],
            1,
        )

    def test_requires_exact_confirmation_new_id_and_undrifted_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirmation"):
            promote_strategy_to_paper(
                self.connection,
                source_strategy_id="sp500-long-v0",
                paper_strategy_id="sp500-long-paper-v1",
                confirmation="yes",
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "new strategy version ID"):
            promote_strategy_to_paper(
                self.connection,
                source_strategy_id="sp500-long-v0",
                paper_strategy_id="sp500-long-v0",
                confirmation="sp500-long-v0",
                now=NOW,
            )

        self.connection.execute(
            "UPDATE strategy_versions SET status = 'backtest' WHERE id = 'sp500-long-v0'"
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            promote_strategy_to_paper(
                self.connection,
                source_strategy_id="sp500-long-v0",
                paper_strategy_id="sp500-long-paper-v1",
                confirmation="sp500-long-paper-v1",
                now=NOW,
            )


if __name__ == "__main__":
    unittest.main()
