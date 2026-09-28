import tempfile
import unittest
import sqlite3
from pathlib import Path
from stock_watch_worker.manual.store import Manual, connect
from stock_watch_worker.manual.execution import reconcile
from stock_watch_worker.manual.accounting import performance
from stock_watch_worker.manual.reporting import refresh


class Broker:
    def __init__(self, identity):
        self.identity = identity
        self.cash = "1000"
        self.orders = {}
        self.position_state = []
        self.posts = 0
        self.uncertain = False

    def account(self):
        return {"id": self.identity, "cash": self.cash, "equity": self.cash}

    def fees(self, after):
        return []

    def positions(self):
        return self.position_state

    def open_orders(self):
        return list(self.orders.values())

    def metadata(self, symbol):
        return {
            "tradable": True,
            "class": "crypto" if symbol == "BTC/USD" else "us_equity",
            "min_order_size": "0.00001",
            "min_trade_increment": "0.00001",
        }

    def quote(self, symbol):
        return {"ask": "10", "bid": "9.99", "at": "test", "source": "fixture"}

    def lookup(self, identity):
        return self.orders.get(identity)

    def market_open(self):
        return True

    def submit_request(self, request):
        self.posts += 1
        if self.uncertain:
            raise TimeoutError()
        result = {"id": request["client_order_id"], "status": "new", "filled_qty": "0"}
        self.orders[request["client_order_id"]] = result
        return result


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "manual.db")
        self.now = 1000
        broker = Broker("manual-paper")
        broker.cash = "1000000"
        self.brokers = {"stocks": broker, "bitcoin": broker}
        self.manual = Manual(
            self.db,
            self.brokers,
            lambda: ["auto-stock", "auto-btc"],
            now=lambda: self.now,
        )
        self.count = 0

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def preview(self, body):
        self.count += 1
        return self.manual.preview(body, "user", "chat", str(self.count))

    def confirm(self, preview, **changes):
        args = {
            "identity": preview["id"],
            "revision": preview["revision"],
            "token": preview["token"],
            "user": "user",
            "chat": "chat",
        }
        return self.manual.confirm(**{**args, **changes})

    def setup_account(self):
        self.confirm(self.preview({"action": "setup", "asset": "combined"}))

    def order(self, **extra):
        return self.preview(
            {
                "action": "order",
                "asset": "stocks",
                "symbol": "ABC",
                "side": "buy",
                "qty": "5",
                "limit": "10",
                **extra,
            }
        )

    def test_setup_distinct_and_never_reset(self):
        self.brokers["bitcoin"].identity = "auto-stock"
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.setup_account()
        self.brokers["bitcoin"].identity = "manual-paper"
        self.setup_account()
        rows = self.db.execute("SELECT asset,account_id,budget FROM accounts ORDER BY asset").fetchall()
        self.assertEqual([(r["asset"], r["account_id"], r["budget"]) for r in rows], [
            ("bitcoin", "manual-paper", "1000"), ("stocks", "manual-paper", "1000")
        ])
        with self.assertRaisesRegex(ValueError, "never reset"):
            self.setup_account()

    def test_requested_broker_balance_uses_separate_durable_virtual_budgets(self):
        broker = self.brokers["stocks"]
        first = self.preview({"action": "setup", "asset": "combined"})
        self.assertEqual(first["preview"]["broker_cash"], "1000000")
        self.assertEqual(first["preview"]["budgets"], {"stocks": "1000", "bitcoin": "1000"})
        broker.cash = "1000000.01"
        with self.assertRaisesRegex(ValueError, "cash changed"):
            self.confirm(first)
        broker.cash = "1000000"
        self.confirm(self.preview({"action": "setup", "asset": "combined"}))
        self.assertEqual(self.manual.spendable_cash("stocks", broker.account()), 1000)
        row = self.db.execute("SELECT * FROM accounts").fetchone()
        self.assertEqual(row["initial_cash"], "1000000")
        self.assertEqual(performance(self.manual, row, broker.account(), [])["total_pnl"], "0")
        for _ in range(10):
            self.confirm(self.order(qty="9"))
        self.db.execute("UPDATE instructions SET status='filled',filled_qty='9',filled_notional='90',reserved_cash='0'")
        self.db.commit()
        broker.cash = "999100"
        self.assertEqual(self.manual.spendable_cash("stocks", broker.account()), 91)
        self.assertEqual(self.manual.spendable_cash("bitcoin", broker.account()), 1000)
        self.confirm(self.order(qty="9"))
        with self.assertRaisesRegex(ValueError, "Insufficient unreserved cash"):
            self.order(qty="9")

    def test_setup_rejects_wrong_broker_balance(self):
        self.brokers["stocks"].cash = "100000"
        with self.assertRaisesRegex(ValueError, "1,000,000"):
            self.preview({"action": "setup", "asset": "combined"})

    def test_both_asset_orders_share_one_broker_without_crossing_budgets(self):
        self.setup_account()
        stock = self.confirm(self.order())
        bitcoin = self.confirm(self.preview({
            "action": "order", "asset": "bitcoin", "symbol": "BTC/USD",
            "side": "buy", "qty": "0.5", "limit": "10",
        }))
        self.assertEqual(stock["status"], "intent")
        self.assertEqual(bitcoin["status"], "intent")
        reconcile(self.manual)
        self.assertEqual(self.brokers["stocks"].posts, 2)
        self.assertEqual(self.db.execute("SELECT COUNT(DISTINCT account_id) FROM instructions").fetchone()[0], 1)
        for action in ("cancel", "protect"):
            with self.assertRaisesRegex(ValueError, "owned"):
                self.preview({
                    "action": action, "asset": "stocks", "instruction": bitcoin["instruction"],
                    **({"stop_loss": "8"} if action == "protect" else {}),
                })
        refresh(self.manual)
        snapshots = self.db.execute("SELECT * FROM snapshots").fetchall()
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["asset"], "combined")

    def test_external_position_cannot_be_sold_or_exit_through_manual_sleeve(self):
        self.setup_account()
        self.brokers["stocks"].position_state = [{"symbol": "ABC", "qty": "5"}]
        with self.assertRaisesRegex(ValueError, "StockWatch-owned"):
            self.preview({"action": "order", "asset": "stocks", "symbol": "ABC", "side": "sell", "qty": "5", "limit": "10"})
        with self.assertRaisesRegex(ValueError, "StockWatch-owned"):
            self.preview({"action": "exit", "asset": "stocks", "symbol": "ABC", "limit": "10"})

    def test_existing_manual_account_baseline_migrates_additively(self):
        old_path = Path(self.temp.name) / "older-manual.db"
        with sqlite3.connect(old_path) as old:
            old.execute("CREATE TABLE accounts(asset TEXT PRIMARY KEY, account_id TEXT UNIQUE NOT NULL, budget TEXT NOT NULL, entry_cap TEXT NOT NULL, confirmed_at REAL NOT NULL)")
            old.execute("INSERT INTO accounts VALUES ('stocks','old-manual','1000','100',1000)")
        upgraded = connect(old_path)
        try:
            self.assertEqual(upgraded.execute("SELECT initial_cash FROM accounts").fetchone()[0], "1000")
            upgraded.execute("INSERT INTO accounts VALUES ('bitcoin','old-manual','1000','100',1000,'1000')")
            self.assertEqual(upgraded.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 2)
        finally:
            upgraded.close()

    def test_confirmation_exact_identity_expiry_single_use(self):
        self.setup_account()
        draft = self.order()
        for changes in (
            {"user": "other"},
            {"chat": "other"},
            {"revision": "other"},
            {"token": "other"},
        ):
            with self.assertRaises(ValueError):
                self.confirm(draft, **changes)
        self.confirm(draft)
        with self.assertRaisesRegex(ValueError, "already used"):
            self.confirm(draft)
        draft = self.order()
        self.now += 121
        with self.assertRaisesRegex(ValueError, "expired"):
            self.confirm(draft)
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM instructions").fetchone()[0], 1
        )

    def test_caps_reservations_account_change_and_duplicate_request(self):
        self.setup_account()
        with self.assertRaisesRegex(ValueError, "entry cap"):
            self.order(qty="10")
        draft = self.order()
        body = {
            "action": "order",
            "asset": "stocks",
            "symbol": "ABC",
            "side": "buy",
            "qty": "5",
            "limit": "10",
        }
        repeated = self.manual.preview(body, "user", "chat", str(self.count))
        self.assertEqual(repeated["id"], draft["id"])
        self.brokers["stocks"].identity = "changed"
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.confirm(draft)

    def test_uncertain_submission_is_not_reposted(self):
        self.setup_account()
        self.confirm(self.order())
        self.brokers["stocks"].uncertain = True
        reconcile(self.manual)
        reconcile(self.manual)
        self.assertEqual(self.brokers["stocks"].posts, 1)
        row = self.db.execute("SELECT * FROM instructions").fetchone()
        self.assertEqual(row["status"], "uncertain")
        self.assertEqual(row["reserved_cash"], "50.50")

    def test_partial_fill_reservations_and_duplicate_reconciliation(self):
        self.setup_account()
        result = self.confirm(self.order())
        reconcile(self.manual)
        broker = self.brokers["stocks"]
        broker.orders[result["instruction"]].update(
            status="partially_filled", filled_qty="2", filled_avg_price="10"
        )
        reconcile(self.manual)
        reconcile(self.manual)
        row = self.db.execute("SELECT * FROM instructions").fetchone()
        self.assertEqual(row["reserved_cash"], "30.30")
        self.assertEqual(self.db.execute("SELECT count(*) FROM fills").fetchone()[0], 1)

    def test_current_condition_expiry_and_price_protection(self):
        self.setup_account()
        self.confirm(self.order(condition="above", threshold="11", limit="11.05"))
        reconcile(self.manual)
        self.assertEqual(self.brokers["stocks"].posts, 0)
        self.now += 86401
        reconcile(self.manual)
        self.assertEqual(
            self.db.execute("SELECT status FROM instructions").fetchone()[0], "expired"
        )
        with self.assertRaisesRegex(ValueError, "0.5%"):
            self.order(condition="above", threshold="10", limit="11")

    def test_no_credentials_or_shorting(self):
        self.manual.brokers = {}
        with self.assertRaisesRegex(ValueError, "unconfigured"):
            self.setup_account()
        self.manual.brokers = self.brokers
        self.setup_account()
        with self.assertRaisesRegex(ValueError, "owns"):
            self.order(side="sell")


if __name__ == "__main__":
    unittest.main()


class CancellationRegressions(unittest.TestCase):
    setUp = ManualTests.setUp
    tearDown = ManualTests.tearDown
    preview = ManualTests.preview
    confirm = ManualTests.confirm
    setup_account = ManualTests.setup_account
    order = ManualTests.order

    def test_cancel_after_uncertain_post_retains_reservation(self):
        self.setup_account()
        result = self.confirm(self.order())
        self.brokers["stocks"].uncertain = True
        reconcile(self.manual)
        self.confirm(
            self.preview(
                {
                    "action": "cancel",
                    "asset": "stocks",
                    "instruction": result["instruction"],
                }
            )
        )
        reconcile(self.manual)
        row = self.db.execute("SELECT * FROM instructions").fetchone()
        self.assertEqual(row["status"], "uncertain")
        self.assertEqual(row["reserved_cash"], "50.50")
        self.assertEqual(self.brokers["stocks"].posts, 1)


class ProtectiveTests(unittest.TestCase):
    setUp = ManualTests.setUp
    tearDown = ManualTests.tearDown
    preview = ManualTests.preview
    confirm = ManualTests.confirm
    setup_account = ManualTests.setup_account
    order = ManualTests.order

    def test_plan_uses_actual_fills_and_persists_without_entry_expiry(self):
        self.setup_account()
        entry = self.confirm(self.order())
        reconcile(self.manual)
        broker = self.brokers["stocks"]
        broker.orders[entry["instruction"]].update(
            status="filled", filled_qty="5", filled_avg_price="10"
        )
        broker.positions = lambda: [{"symbol": "ABC", "qty": "5"}]
        broker.open_orders = lambda: []
        reconcile(self.manual)
        preview = self.preview(
            {
                "action": "protect",
                "asset": "stocks",
                "instruction": entry["instruction"],
                "stop_loss": "10.5",
                "take_profit": "12",
            }
        )
        self.assertTrue(preview["preview"]["already_satisfied"])
        self.confirm(preview)
        self.now += 90000
        reconcile(self.manual)
        children = self.db.execute(
            "SELECT * FROM instructions WHERE side='sell'"
        ).fetchall()
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["qty"], "5")
        self.assertIsNone(children[0]["expires"])
        reconcile(self.manual)
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM instructions WHERE side='sell'"
            ).fetchone()[0],
            1,
        )
        with self.assertRaisesRegex(ValueError, "protective plan"):
            self.order(side="sell")

    def test_cancel_child_requires_canceling_its_protective_plan(self):
        self.test_plan_uses_actual_fills_and_persists_without_entry_expiry()
        child = self.db.execute(
            "SELECT * FROM instructions WHERE side='sell'"
        ).fetchone()
        with self.assertRaisesRegex(ValueError, "protective plan"):
            self.preview(
                {"action": "cancel", "asset": "stocks", "instruction": child["id"]}
            )
