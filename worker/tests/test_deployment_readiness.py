from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from stock_watch_worker.config import load_strategy
from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations, register_strategy
from stock_watch_worker.deployment_readiness import (
    check_deployment_readiness,
    readiness_json,
)


STRATEGY_PATH = Path(__file__).resolve().parents[1] / "config" / "strategy-v0.json"


class DeploymentReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        register_strategy(self.connection, load_strategy(STRATEGY_PATH))

    def tearDown(self) -> None:
        self.connection.close()

    def test_missing_universe_fails_closed(self) -> None:
        result = check_deployment_readiness(
            self.connection,
            strategy_id="sp500-long-v0",
            minimum_universe_members=2,
        )

        self.assertFalse(result.ready)
        self.assertTrue(result.checks["strategy"]["ready"])
        self.assertEqual(
            result.checks["universe"]["reason"], "missing_sp500_snapshot"
        )
        self.assertFalse(json.loads(readiness_json(result))["ready"])

    def test_complete_strategy_universe_and_metadata_are_ready(self) -> None:
        self._insert_universe(
            [
                (1, "AAPL", "320193", 1),
                (2, "MSFT", "789019", 1),
            ]
        )

        result = check_deployment_readiness(
            self.connection,
            strategy_id="sp500-long-v0",
            minimum_universe_members=2,
            minimum_asset_coverage=1,
            minimum_cik_coverage=1,
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.checks["universe"]["members"], 2)
        self.assertEqual(result.checks["asset_metadata"]["coverage"], 1)
        self.assertEqual(result.checks["cik_coverage"]["coverage"], 1)

    def test_partial_asset_or_cik_coverage_is_explicit(self) -> None:
        self._insert_universe(
            [
                (1, "AAPL", "320193", 1),
                (2, "MSFT", None, None),
            ]
        )

        result = check_deployment_readiness(
            self.connection,
            strategy_id="sp500-long-v0",
            minimum_universe_members=2,
            minimum_asset_coverage=0.75,
            minimum_cik_coverage=0.75,
        )

        self.assertFalse(result.ready)
        self.assertEqual(
            result.checks["asset_metadata"]["reason"], "asset_metadata_incomplete"
        )
        self.assertEqual(
            result.checks["cik_coverage"]["reason"], "cik_coverage_incomplete"
        )

    def _insert_universe(
        self, instruments: list[tuple[int, str, str | None, int | None]]
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256,
                survivorship_biased
            ) VALUES (1, 'sp500', '2026-08-26T16:00:00Z', 'fixture', 'hash', 0)
            """
        )
        for instrument_id, symbol, cik, fractionable in instruments:
            self.connection.execute(
                """
                INSERT INTO instruments(id, symbol, cik, fractionable)
                VALUES (?, ?, ?, ?)
                """,
                (instrument_id, symbol, cik, fractionable),
            )
            self.connection.execute(
                "INSERT INTO universe_memberships VALUES (1, ?)",
                (instrument_id,),
            )
        self.connection.commit()


if __name__ == "__main__":
    unittest.main()
