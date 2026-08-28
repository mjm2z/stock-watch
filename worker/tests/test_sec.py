from __future__ import annotations

import gzip
import json
import unittest
import tempfile
from datetime import datetime, timezone

from fakes import FakeTransport, json_response
from stock_watch_worker.capture import JsonResponseCapture
from stock_watch_worker.http import HttpResponse
from stock_watch_worker.providers.sec import MinimumIntervalLimiter, SecClient
from stock_watch_worker.storage import ContentAddressedStore


class FakeLimiter:
    def __init__(self) -> None:
        self.calls = 0

    def wait(self) -> None:
        self.calls += 1


class SecClientTests(unittest.TestCase):
    def test_company_facts_uses_padded_cik_and_identified_user_agent(self) -> None:
        transport = FakeTransport(json_response({"cik": 320193, "facts": {}}))
        limiter = FakeLimiter()
        client = SecClient(
            user_agent="Stock Watch admin@example.test",
            transport=transport,
            limiter=limiter,
        )

        data = client.get_company_facts("320193")

        self.assertEqual(data["cik"], 320193)
        self.assertEqual(
            transport.requests[0].url,
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        )
        self.assertEqual(
            transport.requests[0].headers["User-Agent"],
            "Stock Watch admin@example.test",
        )
        self.assertEqual(limiter.calls, 1)

    def test_company_facts_decodes_gzip_response(self) -> None:
        payload = {"cik": 320193, "facts": {}}
        response = HttpResponse(
            status=200,
            headers={"Content-Encoding": "gzip"},
            body=gzip.compress(json.dumps(payload).encode("utf-8")),
        )
        client = SecClient(
            user_agent="Stock Watch admin@example.test",
            transport=FakeTransport(response),
            limiter=FakeLimiter(),
        )

        self.assertEqual(client.get_company_facts("320193"), payload)

    def test_rejects_unidentified_user_agent_and_invalid_cik(self) -> None:
        with self.assertRaises(ValueError):
            SecClient(user_agent="anonymous")
        client = SecClient(
            user_agent="Stock Watch admin@example.test",
            transport=FakeTransport(),
            limiter=FakeLimiter(),
        )
        with self.assertRaises(ValueError):
            client.get_submissions("not-a-cik")

    def test_minimum_interval_limiter_spaces_requests(self) -> None:
        state = {"now": 100.0}
        sleeps: list[float] = []

        def clock() -> float:
            return state["now"]

        def sleeper(seconds: float) -> None:
            sleeps.append(seconds)
            state["now"] += seconds

        limiter = MinimumIntervalLimiter(
            requests_per_second=8,
            clock=clock,
            sleeper=sleeper,
        )
        limiter.wait()
        limiter.wait()

        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.125)

    def test_successful_sec_response_can_be_captured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = JsonResponseCapture(
                ContentAddressedStore(directory),
                provider="sec",
                clock=lambda: datetime(2026, 8, 20, tzinfo=timezone.utc),
            )
            client = SecClient(
                user_agent="Stock Watch admin@example.test",
                transport=FakeTransport(json_response({"cik": 320193, "facts": {}})),
                limiter=FakeLimiter(),
                response_observer=capture,
            )

            client.get_company_facts(320193)

            self.assertEqual(len(capture.captures), 1)
            self.assertTrue(capture.captures[0].path.exists())


if __name__ == "__main__":
    unittest.main()
