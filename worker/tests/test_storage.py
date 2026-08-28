from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stock_watch_worker.storage import ContentAddressedStore, read_stored_json


class ContentAddressedStoreTests(unittest.TestCase):
    def test_same_payload_is_idempotent_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ContentAddressedStore(directory)
            captured_at = datetime(2026, 8, 20, 14, 45, tzinfo=timezone.utc)
            first = store.put_json(
                dataset="market-bars",
                provider="alpaca",
                logical_key="AAPL/1Day",
                payload={"bars": [{"c": 200}]},
                captured_at=captured_at,
            )
            second = store.put_json(
                dataset="market-bars",
                provider="alpaca",
                logical_key="AAPL/1Day",
                payload={"bars": [{"c": 200}]},
                captured_at=captured_at,
            )

            self.assertFalse(first.already_existed)
            self.assertTrue(second.already_existed)
            self.assertEqual(first.path, second.path)
            self.assertEqual(first.sha256, second.sha256)
            envelope = read_stored_json(first.path)
            self.assertEqual(envelope["payload"]["bars"][0]["c"], 200)
            self.assertEqual(envelope["payload_sha256"], first.sha256)

    def test_changed_payload_creates_a_new_immutable_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ContentAddressedStore(directory)
            timestamp = datetime(2026, 8, 20, tzinfo=timezone.utc)
            first = store.put_json(
                dataset="news",
                provider="alpaca",
                logical_key="daily",
                payload={"id": 1},
                captured_at=timestamp,
            )
            second = store.put_json(
                dataset="news",
                provider="alpaca",
                logical_key="daily",
                payload={"id": 2},
                captured_at=timestamp,
            )

            self.assertNotEqual(first.path, second.path)
            self.assertTrue(first.path.exists())
            self.assertTrue(second.path.exists())

    def test_rejects_naive_capture_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "timezone aware"):
                ContentAddressedStore(directory).put_json(
                    dataset="news",
                    provider="alpaca",
                    logical_key="daily",
                    payload={},
                    captured_at=datetime(2026, 8, 20),
                )


if __name__ == "__main__":
    unittest.main()
