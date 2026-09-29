"""Scoped loopback service. Browser sessions are deliberately not accepted here."""

from contextlib import closing
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.request import urlopen
from ..systems.broker import CryptoBroker
from .broker import ManualBroker
from .execution import reconcile
from .store import Manual, canonical, connect, transaction


def observation():
    try:
        with urlopen("http://127.0.0.1:3012/snapshot", timeout=1) as response:
            return json.load(response)
    except Exception:
        return None


def automated_ids():
    from ..http import UrllibTransport, require_success

    key = os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        raise ValueError("Automated stock account identity is unavailable")
    response = UrllibTransport().request(
        "GET",
        "https://paper-api.alpaca.markets/v2/account",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
        timeout=10,
    )
    return [
        require_success("stock-paper-identity", response)["id"],
        CryptoBroker().account()["id"],
    ]


def instance(path):
    brokers = {}
    for asset in ("stocks", "bitcoin"):
        try:
            brokers[asset] = ManualBroker(asset)
        except ValueError:
            pass
    return Manual(connect(path), brokers, automated_ids, observation=observation)


def handler(path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond(False)

        def do_POST(self):
            self.respond(True)

        def respond(self, post):
            token = os.environ.get("STOCK_WATCH_AUTOBOT_TOKEN", "")
            browser_token = os.environ.get("STOCK_WATCH_BROWSER_SERVICE_TOKEN", "")
            supplied = self.headers.get("Authorization", "")
            browser = bool(
                len(browser_token) >= 32
                and secrets.compare_digest(supplied, "Bearer " + browser_token)
            )
            if not browser and (
                len(token) < 32
                or not secrets.compare_digest(supplied, "Bearer " + token)
            ):
                self.send_response(403)
                self.end_headers()
                return
            manual = instance(path)
            try:
                body = {}
                if post:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 12000:
                        raise ValueError("JSON request must be at most 12 KB")
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("JSON object required")
                    if browser:
                        if (
                            body.get("user") != "browser-operator"
                            or body.get("chat") != "browser"
                        ):
                            raise ValueError("Invalid browser principal")
                    elif str(body.get("user")) != os.environ.get(
                        "STOCK_WATCH_TELEGRAM_USER_ID"
                    ) or str(body.get("chat")) != os.environ.get(
                        "STOCK_WATCH_TELEGRAM_CHAT_ID"
                    ):
                        raise ValueError("Telegram user and chat are not authorized")
                result = self.dispatch(manual, body, post)
                payload = canonical(result).encode()
                self.send_response(200)
            except (ValueError, KeyError, TypeError) as error:
                payload = canonical({"error": str(error)}).encode()
                self.send_response(400)
            except Exception:
                payload = b'{"error":"StockWatch service unavailable"}'
                self.send_response(503)
            finally:
                manual.db.close()
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def dispatch(self, manual, body, post):
            db = manual.db
            if self.path.startswith("/prices?") and not post:
                from urllib.parse import parse_qs, urlsplit

                query = parse_qs(urlsplit(self.path).query)
                asset = query.get("asset", [""])[0]
                symbol = query.get("symbol", [""])[0].upper()
                if asset not in ("stocks", "bitcoin") or len(symbol) > 12:
                    raise ValueError("Choose an account and symbol")
                if asset == "bitcoin" and symbol != "BTC/USD":
                    raise ValueError("Only BTC/USD is supported")
                if asset == "bitcoin":
                    return {
                        "observation": observation(),
                        "source": "Coinbase observations; separate from Alpaca execution",
                    }
                manual.account(asset)
                return {
                    "symbol": symbol,
                    "quote": manual.brokers[asset].quote(symbol),
                    "source": "Alpaca IEX",
                }
            if self.path == "/systems" and not post:
                from .systems import inspect

                return {"systems": inspect()}
            if self.path == "/status" and not post:
                from .capabilities import CAPABILITIES
                return {
                    "capabilities": CAPABILITIES,
                    "allocation_history": [json.loads(r[0]) for r in db.execute("SELECT payload FROM allocation_valuations ORDER BY at DESC LIMIT 600")],
                    "activity": [dict(r) for r in db.execute("SELECT * FROM activity ORDER BY id DESC LIMIT 100")],
                    "manual": "configured"
                    if len(list(db.execute("SELECT * FROM accounts"))) == 2
                    and db.execute("SELECT COUNT(DISTINCT account_id) FROM accounts").fetchone()[0] == 1
                    else "unconfigured",
                    "owned_positions": [dict(r) for r in db.execute("SELECT asset,account_id,symbol,SUM(CASE side WHEN 'buy' THEN CAST(filled_qty AS REAL) ELSE -CAST(filled_qty AS REAL) END) qty FROM instructions GROUP BY asset,account_id,symbol HAVING qty>0")],
                    "accounts": [dict(r) for r in db.execute("SELECT * FROM accounts")],
                    "balances": [
                        json.loads(r["payload"])
                        for r in db.execute("SELECT * FROM snapshots")
                    ],
                    "positions": [
                        {
                            "asset": r["asset"],
                            "at": r["at"],
                            "positions": json.loads(r["payload"])["positions"],
                        }
                        for r in db.execute("SELECT * FROM snapshots")
                    ],
                    "pnl": [
                        {
                            "asset": r["asset"],
                            "at": r["at"],
                            "broker_unrealized_pl": json.loads(r["payload"])[
                                "unrealized_pl"
                            ],
                            "performance": json.loads(r["payload"]).get("performance"),
                        }
                        for r in db.execute("SELECT * FROM snapshots")
                    ],
                    "instructions": [
                        dict(r)
                        for r in db.execute(
                            "SELECT * FROM instructions ORDER BY created DESC LIMIT 100"
                        )
                    ],
                    "drafts": [
                        {
                            "id": r["id"],
                            "state": r["state"],
                            "expires": r["expires"],
                            "preview": json.loads(r["body"])["preview"],
                        }
                        for r in db.execute(
                            "SELECT * FROM drafts ORDER BY expires DESC LIMIT 30"
                        )
                    ],
                    "fills": [
                        dict(r)
                        for r in db.execute(
                            "SELECT * FROM fills ORDER BY observed DESC LIMIT 100"
                        )
                    ],
                    "protective_plans": [
                        dict(r)
                        for r in db.execute(
                            "SELECT * FROM protective_plans ORDER BY created DESC LIMIT 100"
                        )
                    ],
                    "system_jobs": [
                        dict(r)
                        for r in db.execute(
                            "SELECT * FROM system_jobs ORDER BY created DESC LIMIT 30"
                        )
                    ],
                    "health": [dict(r) for r in db.execute("SELECT * FROM health")],
                    "price": observation(),
                }
            if self.path == "/preview" and post:
                return manual.preview(
                    body["command"],
                    str(body["user"]),
                    str(body["chat"]),
                    body["request_id"],
                )
            if self.path == "/confirm" and post:
                return manual.confirm(
                    body["id"],
                    body["revision"],
                    body["token"],
                    str(body["user"]),
                    str(body["chat"]),
                )
            if self.path == "/notifications/claim" and post:
                with transaction(db):
                    uncertain = db.execute(
                        "SELECT count(*) FROM outbox WHERE status='uncertain' AND claimed<?",
                        (time.time() - 120,),
                    ).fetchone()[0]
                    db.execute(
                        "INSERT OR REPLACE INTO health VALUES ('notifications',?,?)",
                        (
                            time.time(),
                            "Uncertain sends require review" if uncertain else None,
                        ),
                    )
                    rows = db.execute(
                        "SELECT * FROM outbox WHERE status='pending' ORDER BY created LIMIT 20"
                    ).fetchall()
                    for row in rows:
                        db.execute(
                            "UPDATE outbox SET status='uncertain',claimed=? WHERE id=?",
                            (time.time(), row["id"]),
                        )
                    return {"notifications": [dict(r) for r in rows]}
            if self.path == "/notifications/ack" and post:
                if body.get("status") not in ("sent", "failed", "uncertain"):
                    raise ValueError("Invalid send status")
                with db:
                    db.execute(
                        "UPDATE outbox SET status=?,result=? WHERE id=? AND status='uncertain'",
                        (body["status"], str(body.get("result", ""))[:300], body["id"]),
                    )
                return {"acknowledged": body["id"]}
            raise ValueError("Unsupported service operation")

    return Handler


def main():
    path = os.environ.get(
        "STOCK_WATCH_MANUAL_DATABASE", "/var/lib/stock-watch/manual-paper.db"
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    with open(path + ".owner.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manual = instance(path)
        server = ThreadingHTTPServer(("127.0.0.1", 3013), handler(path))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        from ..systems.execution_owner import feed_wake

        wake = threading.Event()
        stop = threading.Event()
        latest = {}
        threading.Thread(
            target=feed_wake, args=(wake, latest, stop), daemon=True
        ).start()
        refresh_at = 0
        stocks_at = 0
        dispatch_at = 0
        try:
            while True:
                if time.time() >= refresh_at:
                    from .reporting import refresh

                    refresh(manual)
                    refresh_at = time.time() + 30
                from .systems import dispatch

                dispatch(manual)
                due = time.monotonic() >= stocks_at
                if due or wake.is_set():
                    if time.monotonic() - dispatch_at < 2:
                        stop.wait(2 - (time.monotonic() - dispatch_at))
                    wake.clear()
                    reconcile(manual, ("stocks", "bitcoin") if due else ("bitcoin",))
                    dispatch_at = time.monotonic()
                    if due:
                        stocks_at = dispatch_at + 5
                with manual.db:
                    manual.db.execute(
                        "INSERT OR REPLACE INTO health VALUES ('owner',?,NULL)",
                        (time.time(),),
                    )
                wake.wait(min(1, max(0, stocks_at - time.monotonic())))
        finally:
            stop.set()
            server.shutdown()
            manual.db.close()


if __name__ == "__main__":
    main()
