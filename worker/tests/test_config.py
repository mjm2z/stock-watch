from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from stock_watch_worker.config import load_strategy
from stock_watch_worker.database import (
    MIGRATIONS_DIR,
    apply_migrations,
    register_strategy,
)


STRATEGY_PATH = Path(__file__).resolve().parents[1] / "config" / "strategy-v0.json"


class StrategyConfigTests(unittest.TestCase):
    def test_packaged_default_matches_source_strategy(self) -> None:
        source = STRATEGY_PATH.read_text(encoding="utf-8")
        packaged = (
            STRATEGY_PATH.parents[1]
            / "src/stock_watch_worker/strategy-v0.json"
        ).read_text(encoding="utf-8")

        self.assertEqual(json.loads(packaged), json.loads(source))

    def test_loads_accepted_strategy_and_generates_stable_hash(self) -> None:
        first = load_strategy(STRATEGY_PATH)
        second = load_strategy(STRATEGY_PATH)

        self.assertEqual(first.id, "sp500-long-v0")
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(len(first.sha256), 64)

    def test_refuses_live_mode(self) -> None:
        strategy = json.loads(STRATEGY_PATH.read_text(encoding="utf-8"))
        strategy["execution"]["mode"] = "live"
        with self.assertRaisesRegex(ValueError, "execution mode must be paper"):
            self._load_modified(strategy)

    def test_refuses_live_endpoint_even_when_mode_says_paper(self) -> None:
        strategy = json.loads(STRATEGY_PATH.read_text(encoding="utf-8"))
        strategy["execution"]["alpaca_base_url"] = "https://api.alpaca.markets"
        with self.assertRaisesRegex(ValueError, "paper endpoint"):
            self._load_modified(strategy)

    def test_requires_accepted_market_scan_windows(self) -> None:
        strategy = json.loads(STRATEGY_PATH.read_text(encoding="utf-8"))
        strategy["scan_windows"][1]["time"] = "16:00"
        with self.assertRaisesRegex(ValueError, "09:45 and 16:15"):
            self._load_modified(strategy)

    def test_registered_strategy_is_immutable(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        try:
            apply_migrations(connection, MIGRATIONS_DIR)
            strategy = load_strategy(STRATEGY_PATH)
            self.assertTrue(register_strategy(connection, strategy))
            self.assertFalse(register_strategy(connection, strategy))

            changed = json.loads(STRATEGY_PATH.read_text(encoding="utf-8"))
            changed["name"] = "Changed without a new id"
            changed_strategy = self._load_modified(changed)
            with self.assertRaisesRegex(ValueError, "immutable"):
                register_strategy(connection, changed_strategy)
        finally:
            connection.close()

    def _load_modified(self, data: dict) -> object:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "strategy.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return load_strategy(path)


if __name__ == "__main__":
    unittest.main()
