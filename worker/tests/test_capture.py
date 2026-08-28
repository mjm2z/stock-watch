from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone

from stock_watch_worker.capture import JsonResponseCapture
from stock_watch_worker.storage import ContentAddressedStore, read_stored_json


class ResponseCaptureTests(unittest.TestCase):
    def test_captures_exact_decoded_response_with_request_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = JsonResponseCapture(
                ContentAddressedStore(directory),
                provider="alpaca",
                clock=lambda: datetime(2026, 8, 20, 14, 45, tzinfo=timezone.utc),
            )
            payload = {"bars": {"AAPL": [{"c": 200}]}}
            capture(
                "/v2/stocks/bars",
                {"symbols": "AAPL", "timeframe": "1Day"},
                payload,
            )

            self.assertEqual(len(capture.captures), 1)
            stored = read_stored_json(capture.captures[0].path)
            self.assertEqual(stored["payload"], payload)
            self.assertEqual(stored["dataset"], "v2-stocks-bars")
            self.assertEqual(stored["provider"], "alpaca")


if __name__ == "__main__":
    unittest.main()
