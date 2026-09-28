"""Durable previews, reservations and order intents in a separate database."""

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
import secrets
import sqlite3
import time
import uuid

D = Decimal
TERMINAL = ("filled", "canceled", "expired", "rejected")


def money(value):
    try:
        result = D(str(value))
    except InvalidOperation as error:
        raise ValueError("A positive finite number is required") from error
    if not result.is_finite() or result <= 0:
        raise ValueError("A positive finite number is required")
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def connect(path):
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS accounts(asset TEXT PRIMARY KEY, account_id TEXT UNIQUE NOT NULL,
        budget TEXT NOT NULL, entry_cap TEXT NOT NULL, confirmed_at REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
        user_id TEXT NOT NULL, chat_id TEXT NOT NULL, revision TEXT NOT NULL, body TEXT NOT NULL,
        token_hash TEXT NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL DEFAULT 'preview', result TEXT);
      CREATE TABLE IF NOT EXISTS instructions(id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
        asset TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, qty TEXT NOT NULL,
        limit_price TEXT NOT NULL, condition TEXT, threshold TEXT, expires REAL,
        status TEXT NOT NULL, request TEXT NOT NULL, reserved_cash TEXT NOT NULL,
        reserved_qty TEXT NOT NULL, broker_id TEXT, filled_qty TEXT NOT NULL DEFAULT '0',
        filled_notional TEXT NOT NULL DEFAULT '0', response TEXT, audit TEXT NOT NULL,
        created REAL NOT NULL, updated REAL NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS fills(instruction_id TEXT NOT NULL, cumulative_qty TEXT NOT NULL,
        cumulative_notional TEXT NOT NULL, observed REAL NOT NULL, response TEXT NOT NULL,
        PRIMARY KEY(instruction_id,cumulative_qty));
      CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, created REAL NOT NULL, message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', claimed REAL, result TEXT);
      CREATE TABLE IF NOT EXISTS integration_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS fee_activities(account_id TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,observed REAL NOT NULL,PRIMARY KEY(account_id,id));
      CREATE TABLE IF NOT EXISTS protective_plans(id TEXT PRIMARY KEY,parent TEXT NOT NULL REFERENCES instructions(id),stop_loss TEXT,take_profit TEXT,status TEXT NOT NULL,attribution TEXT NOT NULL,created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS snapshots(asset TEXT PRIMARY KEY,at REAL NOT NULL,payload TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS system_jobs(id TEXT PRIMARY KEY,body TEXT NOT NULL,attribution TEXT NOT NULL,created REAL NOT NULL,state TEXT NOT NULL DEFAULT 'queued',result TEXT);
      CREATE TABLE IF NOT EXISTS health(component TEXT PRIMARY KEY, at REAL NOT NULL, error TEXT);
    """)
    return db


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


def notify(db, identity, message, now):
    db.execute(
        "INSERT OR IGNORE INTO outbox(id,created,message) VALUES (?,?,?)",
        (identity, now, message),
    )


class Manual:
    def __init__(
        self, db, brokers, automated_ids, *, now=time.time, observation=lambda: None
    ):
        self.db, self.brokers, self.automated_ids = db, brokers, automated_ids
        self.now, self.observation = now, observation

    def account(self, asset, setup=False):
        if set(self.brokers) != {"stocks", "bitcoin"}:
            raise ValueError(
                "Manual trading unconfigured: provision two separate paper accounts"
            )
        accounts = {name: broker.account() for name, broker in self.brokers.items()}
        identifiers = {a["id"] for a in accounts.values()}
        automated = set(self.automated_ids())
        if len(automated) != 2 or len(identifiers) != 2 or identifiers & automated:
            raise ValueError("Verify four distinct actual paper-account identities")
        account = accounts[asset]
        row = self.db.execute(
            "SELECT * FROM accounts WHERE asset=?", (asset,)
        ).fetchone()
        if not setup and (not row or row["account_id"] != account["id"]):
            raise ValueError(
                "Account setup confirmation is required or account identity changed"
            )
        return account

    def validate(self, body):
        if not isinstance(body, dict):
            raise ValueError("Structured command required")
        if body.get("action") == "system":
            from .systems import validate

            return validate(body)
        if body.get("action") == "exit":
            if set(body) - {"action", "asset", "symbol", "limit", "expires"}:
                raise ValueError("Unsupported exit fields")
            asset = body.get("asset")
            if asset not in ("stocks", "bitcoin"):
                raise ValueError("Choose stocks or bitcoin")
            self.account(asset)
            symbol = str(body.get("symbol", "")).upper()
            positions = self.brokers[asset].positions()
            owned = sum(
                (
                    D(p["qty"])
                    for p in positions
                    if p["symbol"].replace("/", "") == symbol.replace("/", "")
                ),
                D(0),
            )
            result = self.validate(
                {
                    "action": "order",
                    "asset": asset,
                    "symbol": symbol,
                    "side": "sell",
                    "qty": str(owned),
                    "limit": body.get("limit"),
                    **({"expires": body["expires"]} if "expires" in body else {}),
                }
            )
            return {**result, "action": "exit"}
        allowed = {
            "action",
            "asset",
            "symbol",
            "side",
            "qty",
            "limit",
            "condition",
            "threshold",
            "expires",
            "instruction",
            "order_type",
            "stop_price",
            "stop_loss",
            "take_profit",
        }
        if set(body) - allowed:
            raise ValueError(
                "Unsupported fields: " + ", ".join(sorted(set(body) - allowed))
            )
        asset = body.get("asset")
        if asset not in ("stocks", "bitcoin"):
            raise ValueError("Choose stocks or bitcoin")
        action = body.get("action")
        if action not in ("setup", "order", "cancel", "protect", "cancel_plan"):
            raise ValueError("Supported actions: setup, order, cancel")
        fields = {
            "setup": {"action", "asset"},
            "cancel": {"action", "asset", "instruction"},
            "cancel_plan": {"action", "asset", "instruction"},
            "protect": {"action", "asset", "instruction", "stop_loss", "take_profit"},
            "order": {
                "action",
                "asset",
                "symbol",
                "side",
                "qty",
                "limit",
                "condition",
                "threshold",
                "expires",
                "order_type",
                "stop_price",
            },
        }
        if set(body) - fields[action]:
            raise ValueError("Fields are unsupported for this action")
        account = self.account(asset, setup=action == "setup")
        broker = self.brokers[asset]
        if action in ("protect", "cancel_plan"):
            from .protection import validate

            return validate(self, body, account)
        if action == "setup":
            if self.db.execute(
                "SELECT 1 FROM accounts WHERE asset=?", (asset,)
            ).fetchone():
                raise ValueError(
                    "Account setup already confirmed; accounts are never reset"
                )
            if (
                abs(D(account["cash"]) - 1000) > D(".01")
                or broker.positions()
                or broker.open_orders()
            ):
                raise ValueError(
                    "Setup requires an empty $1,000 paper account; no reset is performed"
                )
            return {
                **body,
                "account_id": account["id"],
                "budget": "1000",
                "entry_cap": "100",
            }
        if action == "cancel":
            row = self.db.execute(
                "SELECT * FROM instructions WHERE id=? AND account_id=?",
                (body.get("instruction"), account["id"]),
            ).fetchone()
            if not row or row["status"] in TERMINAL:
                raise ValueError(
                    "Select a pending instruction owned by this manual account"
                )
            if json.loads(row["audit"]).get("protective_plan"):
                raise ValueError(
                    "Cancel the protective plan to stop its exit management"
                )
            return {**body, "account_id": account["id"]}
        symbol = str(body.get("symbol", "")).upper()
        if asset == "bitcoin" and symbol != "BTC/USD":
            raise ValueError("Bitcoin supports BTC/USD only")
        if self.db.execute(
            "SELECT 1 FROM protective_plans p JOIN instructions i ON i.id=p.parent WHERE i.account_id=? AND i.symbol=? AND p.status NOT IN ('closed','canceled')",
            (account["id"], symbol),
        ).fetchone():
            raise ValueError(
                "Cancel this symbol’s protective plan and settle its exits before new manual orders"
            )
        metadata = broker.metadata(symbol)
        if not metadata.get("tradable") or metadata.get("class") != (
            "crypto" if asset == "bitcoin" else "us_equity"
        ):
            raise ValueError(
                "Only tradable long-only stocks/ETFs and BTC/USD are supported"
            )
        side = body.get("side")
        if side not in ("buy", "sell"):
            raise ValueError("Choose buy or sell")
        qty = money(body.get("qty"))
        price = money(body.get("limit"))
        if asset == "stocks" and qty != qty.to_integral_value():
            raise ValueError("Stock limit orders require whole shares")
        increment = D(metadata.get("min_trade_increment") or "0.000000001")
        if asset == "bitcoin" and (
            qty < D(metadata["min_order_size"]) or qty % increment
        ):
            raise ValueError("Quantity violates broker minimum/increment")
        order_type = body.get("order_type", "limit")
        if order_type not in ("limit", "stop_limit"):
            raise ValueError("Only limit and stop_limit broker orders are supported")
        if order_type == "stop_limit":
            stop = money(body.get("stop_price"))
            if body.get("condition"):
                raise ValueError("Cannot combine a broker stop with a local condition")
            if (side == "buy" and price < stop) or (side == "sell" and price > stop):
                raise ValueError("Stop-limit price must protect the selected side")
        elif body.get("stop_price") is not None:
            raise ValueError("Stop price requires stop_limit order type")
        condition = body.get("condition")
        if condition not in (None, "above", "below"):
            raise ValueError("Choose above or below")
        if not condition and body.get("threshold") is not None:
            raise ValueError("Threshold requires above/below condition")
        threshold = money(body.get("threshold")) if condition else None
        quote = broker.quote(symbol)
        reference = money(quote["ask"] if side == "buy" else quote["bid"])
        # Every custom triggered entry has a fixed, previewed protection price.
        if condition and side == "buy" and price > threshold * D("1.005"):
            raise ValueError(
                "Triggered buy limit must be within 0.5% above the trigger"
            )
        expiry = float(body.get("expires") or self.now() + 86400)
        if not self.now() < expiry <= self.now() + 86400:
            raise ValueError("Entry instruction expiry must be within 24 hours")
        observation = self.observation() if asset == "bitcoin" and condition else None
        observed = (
            D(str(observation["price"]))
            if observation and observation.get("fresh")
            else reference
            if asset == "stocks"
            else None
        )
        satisfied = bool(
            condition
            and observed is not None
            and (
                observed >= threshold if condition == "above" else observed <= threshold
            )
        )
        if order_type == "stop_limit":
            satisfied = reference >= stop if side == "buy" else reference <= stop
        reservations = self.db.execute(
            "SELECT * FROM instructions WHERE account_id=? AND status NOT IN ('filled','canceled','expired','rejected')",
            (account["id"],),
        ).fetchall()
        if len(reservations) >= 20:
            raise ValueError("At most 20 pending instructions per manual account")
        known = {r["broker_id"] for r in reservations if r["broker_id"]}
        if any(o["id"] not in known for o in broker.open_orders()):
            raise ValueError("External pending orders require reconciliation")
        reserve_cash = qty * price * D("1.01") if side == "buy" else D(0)
        if side == "buy":
            if reserve_cash > 100:
                raise ValueError("$100 entry cap includes fee allowance")
            reserved = sum((D(r["reserved_cash"]) for r in reservations), D(0))
            if reserve_cash > min(D(account["cash"]), D(1000)) - reserved:
                raise ValueError("Insufficient unreserved cash")
        else:
            owned = sum(
                (
                    D(p["qty"])
                    for p in broker.positions()
                    if p["symbol"].replace("/", "") == symbol.replace("/", "")
                ),
                D(0),
            )
            reserved = sum(
                (D(r["reserved_qty"]) for r in reservations if r["symbol"] == symbol),
                D(0),
            )
            if qty > owned - reserved:
                raise ValueError(
                    "Cannot sell more than this manual account owns and has unreserved"
                )
        return {
            **body,
            "symbol": symbol,
            "qty": str(qty),
            "limit": str(price),
            "expires": expiry,
            "account_id": account["id"],
            "reserved_cash": str(reserve_cash),
            "reserved_qty": str(qty if side == "sell" else 0),
            "already_satisfied": satisfied,
            "quote": quote,
            "observation": observation,
            "requires_online": bool(condition),
            "fee_allowance": "1%",
            "trigger_allowance": "0.5%",
        }

    def preview(self, body, user, chat, request):
        if not request or len(request) > 160:
            raise ValueError("A stable request ID is required")
        with transaction(self.db):
            old = self.db.execute(
                "SELECT * FROM drafts WHERE request_id=?", (request,)
            ).fetchone()
            if old:
                if (
                    old["user_id"] != user
                    or old["chat_id"] != chat
                    or json.loads(old["body"])["command"] != body
                ):
                    raise ValueError("Request ID was reused for a different draft")
                return {
                    "id": old["id"],
                    "state": old["state"],
                    "preview": json.loads(old["body"])["preview"],
                    "confirmation": "Previously issued; create a new preview if the token was lost",
                }
            preview = self.validate(body)
            identity = uuid.uuid4().hex
            token = secrets.token_urlsafe(24)
            document = canonical({"command": body, "preview": preview})
            revision = hashlib.sha256(document.encode()).hexdigest()
            expires = self.now() + 120
            self.db.execute(
                "INSERT INTO drafts(id,request_id,user_id,chat_id,revision,body,token_hash,expires) VALUES (?,?,?,?,?,?,?,?)",
                (
                    identity,
                    request,
                    user,
                    chat,
                    revision,
                    document,
                    hashlib.sha256(token.encode()).hexdigest(),
                    expires,
                ),
            )
            return {
                "id": identity,
                "revision": revision,
                "token": token,
                "expires": expires,
                "preview": preview,
            }

    def confirm(self, identity, revision, token, user, chat):
        with transaction(self.db):
            row = self.db.execute(
                "SELECT * FROM drafts WHERE id=?", (identity,)
            ).fetchone()
            if (
                not row
                or row["user_id"] != user
                or row["chat_id"] != chat
                or row["revision"] != revision
                or not secrets.compare_digest(
                    row["token_hash"], hashlib.sha256(token.encode()).hexdigest()
                )
            ):
                raise ValueError(
                    "Confirmation does not match this draft revision/user/chat"
                )
            if row["state"] != "preview":
                raise ValueError("Confirmation already used")
            if row["expires"] <= self.now():
                raise ValueError("Confirmation expired; preview again")
            document = json.loads(row["body"])
            body = document["command"]
            current = self.validate(
                {**body, "expires": document["preview"]["expires"]}
                if body["action"] in ("order", "exit")
                else body
            )
            if (
                body["action"] == "exit"
                and current["qty"] != document["preview"]["qty"]
            ):
                raise ValueError("Position changed; preview the exit again")
            if current["account_id"] != document["preview"]["account_id"]:
                raise ValueError("Account identity changed")
            if (
                body["action"] == "system"
                and current["version_hash"] != document["preview"]["version_hash"]
            ):
                raise ValueError("System revision changed")
            action = body["action"]
            now = self.now()
            if action == "system":
                job = "telegram-system-" + identity
                self.db.execute(
                    "INSERT INTO system_jobs(id,body,attribution,created) VALUES (?,?,?,?)",
                    (
                        job,
                        canonical(body),
                        canonical({"user": user, "chat": chat, "revision": revision}),
                        now,
                    ),
                )
                result = {"system_job": job, "state": "queued"}
            elif action == "setup":
                self.db.execute(
                    "INSERT INTO accounts VALUES (?,?,?,?,?)",
                    (body["asset"], current["account_id"], "1000", "100", now),
                )
                result = {
                    "configured": body["asset"],
                    "account_id": current["account_id"],
                }
            elif action == "protect":
                plan = "plan-" + identity
                self.db.execute(
                    "INSERT INTO protective_plans VALUES (?,?,?,?,?,?,?)",
                    (
                        plan,
                        body["instruction"],
                        current["stop_loss"],
                        current["take_profit"],
                        "active",
                        canonical({"user": user, "chat": chat, "revision": revision}),
                        now,
                    ),
                )
                result = {"protective_plan": plan, "status": "active"}
            elif action == "cancel_plan":
                self.db.execute(
                    "UPDATE protective_plans SET status='cancel_requested' WHERE id=?",
                    (current["plan"],),
                )
                result = {
                    "protective_plan": current["plan"],
                    "status": "cancel_requested",
                }
            elif action == "cancel":
                self.db.execute(
                    "UPDATE instructions SET cancel_requested=1,updated=? WHERE id=?",
                    (now, body["instruction"]),
                )
                result = {"cancel_requested": body["instruction"]}
            else:
                order = "manual-" + identity
                request = {
                    "symbol": current["symbol"],
                    "side": current["side"],
                    "qty": current["qty"],
                    "type": body.get("order_type", "limit"),
                    "limit_price": current["limit"],
                    "time_in_force": "gtc" if body["asset"] == "bitcoin" else "day",
                    "client_order_id": order,
                }
                if body.get("order_type") == "stop_limit":
                    request["stop_price"] = str(money(body["stop_price"]))
                self.db.execute(
                    """INSERT INTO instructions(id,account_id,asset,symbol,side,qty,limit_price,condition,threshold,expires,status,request,reserved_cash,reserved_qty,audit,created,updated)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        order,
                        current["account_id"],
                        body["asset"],
                        current["symbol"],
                        current["side"],
                        current["qty"],
                        current["limit"],
                        body.get("condition"),
                        str(body["threshold"]) if body.get("condition") else None,
                        current["expires"],
                        "armed" if body.get("condition") else "intent",
                        canonical(request),
                        current["reserved_cash"],
                        current["reserved_qty"],
                        canonical(
                            {
                                "user": user,
                                "chat": chat,
                                "draft": identity,
                                "revision": revision,
                                "preview": current,
                            }
                        ),
                        now,
                        now,
                    ),
                )
                result = {
                    "instruction": order,
                    "status": "armed" if body.get("condition") else "intent",
                }
            self.db.execute(
                "UPDATE drafts SET state='confirmed',result=? WHERE id=?",
                (canonical(result), identity),
            )
            notify(
                self.db,
                "confirmed:" + identity,
                "Manual paper confirmation: " + canonical(result),
                now,
            )
            return result
