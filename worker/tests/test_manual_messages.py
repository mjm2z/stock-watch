import json
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from stock_watch_worker.manual import messages
from stock_watch_worker.manual.reporting import refresh
import test_manual_paper as fixtures


class MessageTests(unittest.TestCase):
    def snapshot(self, at=1000):
        return {"at": at, "equity": "1000015", "allocations": [
            {"asset": "stocks", "equity": "1025", "net_pnl": "25", "positions": [{"symbol": "ABC"}]},
            {"asset": "bitcoin", "equity": "990", "net_pnl": "-10", "positions": []},
        ]}

    def test_compact_allocation_digest(self):
        text = messages.digest([self.snapshot()], [{"status": "intent"}, {"status": "filled"}], [], 1000)
        self.assertIn("Stocks: $1,025.00 · P/L +$25.00", text)
        self.assertIn("Bitcoin: $990.00 · P/L −$10.00", text)
        self.assertIn("since setup: +$15.00", text)
        self.assertIn("1 position · 1 pending order", text)
        self.assertNotIn("1,000,015", text)
        self.assertNotIn("Attention", text)
        self.assertNotIn("{", text)
        self.assertEqual(len(text.splitlines()), 6)

    def test_missing_unreconciled_stale_and_uncertain(self):
        snapshot = self.snapshot()
        snapshot["allocations"][0].update(equity=None, net_pnl=None, unavailable_reason="Combined broker account does not reconcile")
        text = messages.digest([snapshot], [{"status": "uncertain"}], [{"error": "offline"}], 2000)
        for expected in ("Stocks: unavailable", "since setup: unavailable", "stale", "does not reconcile", "before retrying", "Service issue"):
            self.assertIn(expected, text)
        self.assertIn("Stocks: unavailable", messages.digest([], [], [], 2000))

    def test_zero_is_known_but_nonfinite_is_unavailable(self):
        self.assertEqual(messages.dollars("0", True), "$0.00")
        for value in (None, "NaN", "Infinity", "garbage"):
            self.assertEqual(messages.dollars(value), "unavailable")

    def test_fill_precision_and_unfilled_rejection(self):
        text = messages.order_event({"symbol": "BTC/USD", "side": "buy"}, "partially_filled", "0.00012345", "60000.1234")
        self.assertIn("Partially filled", text)
        self.assertIn("0.00012345 at $60000.1234 average", text)
        text = messages.order_event({"symbol": "ABC", "side": "buy"}, "rejected", "0", "0")
        self.assertIn("No fills reported", text)
        self.assertNotIn("at $0", text)

    def test_system_events_never_dump_payloads(self):
        payload = {"qty": "0.00012345", "side": "buy", "account_id": "private-id", "nested": {"secret": "hidden"}}
        text = messages.system_event("order_intent", "system-id", payload)
        self.assertIn("Order queued", text)
        self.assertIn("0.00012345", text)
        self.assertNotIn("private-id", text)
        self.assertNotIn("hidden", text)
        self.assertIn("Details:", messages.system_event("new_fill_event", "system-id", payload))
        self.assertIn("existing exits continue", messages.system_event("operator_pause", "system-id", {}))

    def test_whole_line_bounding(self):
        text = messages.bounded(["first", "😀" * 4000, "last"])
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 3900)
        self.assertTrue(text.startswith("first\n"))
        self.assertNotIn("last", text)
        self.assertIn("More details", text)

    def test_confirmation_is_queued_not_filled(self):
        text = messages.confirmation({"instruction": "manual-1", "status": "intent"})
        self.assertIn("not filled yet", text)
        self.assertNotIn("{", text)
        self.assertIn("awaiting reconciliation", messages.confirmation({"cancel_requested": "manual-1"}))


class NotificationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ManualTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.setup_account()

    def test_digest_uses_existing_identity_and_is_not_repeated(self):
        f = self.fixture
        f.now = datetime(2026, 10, 12, 20, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()
        with patch.dict("os.environ", {"STOCK_WATCH_DIGEST_TIME": "20:00"}):
            refresh(f.manual)
            refresh(f.manual)
        rows = f.db.execute("SELECT id,message FROM outbox WHERE id LIKE 'digest:%'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "digest:2026-10-12")
        self.assertIn("Stocks: $1,000.00", rows[0]["message"])
        self.assertNotIn("1000000", rows[0]["message"])
        self.assertIn("0 pending orders", rows[0]["message"])
        snapshots = json.loads(f.db.execute("SELECT payload FROM snapshots").fetchone()[0])
        self.assertEqual(snapshots["cash"], "1000000")

    def test_confirmation_durable_message_is_readable(self):
        f = self.fixture
        result = f.confirm(f.order())
        text = f.db.execute("SELECT message FROM outbox ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        self.assertIn(result["instruction"], text)
        self.assertIn("not filled yet", text)
        self.assertNotIn("{", text)
