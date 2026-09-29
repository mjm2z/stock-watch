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
      CREATE TABLE IF NOT EXISTS accounts(asset TEXT PRIMARY KEY, account_id TEXT NOT NULL,
        budget TEXT NOT NULL, entry_cap TEXT NOT NULL, confirmed_at REAL NOT NULL,
        initial_cash TEXT NOT NULL DEFAULT '1000');
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
      CREATE INDEX IF NOT EXISTS instructions_scope ON instructions(asset,symbol,created DESC);
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
    if "initial_cash" not in {
        row[1] for row in db.execute("PRAGMA table_info(accounts)")
    }:
        db.execute("ALTER TABLE accounts ADD COLUMN initial_cash TEXT NOT NULL DEFAULT '1000'")
        db.commit()
    # Earlier staging used one broker identity per asset. Preserve its rows while
    # removing the account-id uniqueness constraint for the shared manual account.
    for index in db.execute("PRAGMA index_list(accounts)").fetchall():
        if index[2] and [r[2] for r in db.execute(f'PRAGMA index_info("{index[1]}")')] == ["account_id"]:
            try:
                db.executescript("""
                  BEGIN IMMEDIATE;
                  CREATE TABLE accounts_shared(asset TEXT PRIMARY KEY,account_id TEXT NOT NULL,
                    budget TEXT NOT NULL,entry_cap TEXT NOT NULL,confirmed_at REAL NOT NULL,
                    initial_cash TEXT NOT NULL);
                  INSERT INTO accounts_shared SELECT asset,account_id,budget,entry_cap,confirmed_at,initial_cash FROM accounts;
                  DROP TABLE accounts;
                  ALTER TABLE accounts_shared RENAME TO accounts;
                  COMMIT;
                """)
            except Exception:
                db.rollback()
                raise
            break
    # Prospective transition history: never synthesize earlier order events.
    db.executescript("""
      CREATE TABLE IF NOT EXISTS state_revision(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL);
      INSERT OR IGNORE INTO state_revision VALUES(1,0);
      CREATE TABLE IF NOT EXISTS allocation_valuations(account_id TEXT NOT NULL,asset TEXT NOT NULL,minute INTEGER NOT NULL,at REAL NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(account_id,asset,minute));
      CREATE INDEX IF NOT EXISTS allocation_valuations_latest ON allocation_valuations(at DESC);
      CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT,
        instruction_id TEXT NOT NULL,asset TEXT NOT NULL,account_id TEXT NOT NULL,
        symbol TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,at REAL NOT NULL,payload TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS activity_scope ON activity(asset,symbol,id DESC);
      CREATE TRIGGER IF NOT EXISTS instruction_created AFTER INSERT ON instructions BEGIN
        INSERT INTO activity(instruction_id,asset,account_id,symbol,kind,status,at,payload)
        VALUES(NEW.id,NEW.asset,NEW.account_id,NEW.symbol,'intent',NEW.status,NEW.created,
          json_object('request',json(NEW.request),'audit',json(NEW.audit)));
      END;
      CREATE TRIGGER IF NOT EXISTS instruction_transition AFTER UPDATE ON instructions
      WHEN OLD.status != NEW.status OR OLD.filled_qty != NEW.filled_qty OR OLD.cancel_requested != NEW.cancel_requested BEGIN
        INSERT INTO activity(instruction_id,asset,account_id,symbol,kind,status,at,payload)
        VALUES(NEW.id,NEW.asset,NEW.account_id,NEW.symbol,
          CASE WHEN OLD.filled_qty != NEW.filled_qty THEN 'fill'
               WHEN OLD.cancel_requested != NEW.cancel_requested THEN 'cancel_requested' ELSE 'status' END,
          NEW.status,NEW.updated,json_object('previous_status',OLD.status,'filled_qty',NEW.filled_qty,
          'filled_notional',NEW.filled_notional,'broker_id',NEW.broker_id,'audit',json(NEW.audit)));
      END;
    """)
    for table in ('accounts', 'drafts', 'instructions', 'protective_plans', 'fee_activities'):
        for operation in ('INSERT', 'UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS revision_{table}_{operation} AFTER {operation} ON {table} BEGIN UPDATE state_revision SET revision=revision+1 WHERE id=1; END")
    db.commit()
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
                "Manual trading unconfigured: provision one dedicated paper account"
            )
        accounts = {name: broker.account() for name, broker in self.brokers.items()}
        identifiers = {a["id"] for a in accounts.values()}
        automated = set(self.automated_ids())
        if len(automated) != 2 or len(identifiers) != 1 or identifiers & automated:
            raise ValueError("Verify one manual paper account distinct from both automated accounts")
        account = accounts[asset]
        row = self.db.execute(
            "SELECT * FROM accounts WHERE asset=?", (asset,)
        ).fetchone()
        if not setup and (not row or row["account_id"] != account["id"]):
            raise ValueError(
                "Account setup confirmation is required or account identity changed"
            )
        return account

    def spendable_cash(self, asset, account):
        """Each asset has a durable virtual allocation within one broker account."""
        row = self.db.execute("SELECT * FROM accounts WHERE asset=?", (asset,)).fetchone()
        if not row or row["account_id"] != account["id"]:
            raise ValueError("Manual account setup is required")
        budget = D(row["budget"])
        broker_cash = D(str(account["cash"]))
        if not all(value.is_finite() for value in (budget, broker_cash)):
            raise ValueError("Invalid broker cash or manual allocation")
        orders = self.db.execute(
            "SELECT side,filled_notional FROM instructions WHERE account_id=? AND asset=?",
            (account["id"], asset),
        )
        spent = sum(
            (D(order["filled_notional"]) * (D("1.01") if order["side"] == "buy" else -D("0.99"))
             for order in orders), D(0)
        )
        # The 1% allowance remains against cumulative fills until actual fees are
        # reconciled; activity in the other sleeve never replenishes this sleeve.
        return max(D(0), min(budget, budget - spent, broker_cash))

    def attributed_qty(self, asset, symbol):
        """Quantity acquired through this manual sleeve, excluding external holdings."""
        row = self.db.execute("SELECT account_id FROM accounts WHERE asset=?", (asset,)).fetchone()
        if not row:
            raise ValueError("Manual account setup is required")
        orders = self.db.execute(
            "SELECT side,filled_qty FROM instructions WHERE asset=? AND account_id=? AND REPLACE(symbol,'/','')=?",
            (asset, row["account_id"], symbol.replace("/", "")),
        )
        return max(D(0), sum(
            (D(order["filled_qty"]) * (1 if order["side"] == "buy" else -1)
             for order in orders), D(0)
        ))

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
            owned = min(owned, self.attributed_qty(asset, symbol))
            if owned <= 0:
                raise ValueError("No StockWatch-owned sleeve quantity to exit")
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
            "notional",
            "time_in_force",
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
        action = body.get("action")
        if action == "setup":
            if asset != "combined":
                raise ValueError("Set up the shared stocks and Bitcoin account together")
        elif asset not in ("stocks", "bitcoin"):
            raise ValueError("Choose stocks or bitcoin")
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
                "notional",
                "time_in_force",
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
        lookup_asset = "stocks" if action == "setup" else asset
        account = self.account(lookup_asset, setup=action == "setup")
        broker = self.brokers[lookup_asset]
        if action in ("protect", "cancel_plan"):
            from .protection import validate

            return validate(self, body, account)
        if action == "setup":
            if self.db.execute(
                "SELECT 1 FROM accounts",
            ).fetchone():
                raise ValueError(
                    "Account setup already confirmed; accounts are never reset"
                )
            broker_cash = money(account["cash"])
            if abs(broker_cash - D("1000000")) > D(".01") or broker.positions() or broker.open_orders():
                raise ValueError(
                    "Setup requires one fresh empty paper account with $1,000,000 simulated cash; no reset is performed"
                )
            return {
                **body,
                "account_id": account["id"],
                "budgets": {"stocks": "1000", "bitcoin": "1000"},
                "entry_cap": "100",
                "broker_cash": str(broker_cash),
            }
        if action == "cancel":
            row = self.db.execute(
                "SELECT * FROM instructions WHERE id=? AND account_id=? AND asset=?",
                (body.get("instruction"), account["id"], asset),
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
        from .capabilities import validate_order
        terms = validate_order(body, metadata, asset, side)
        qty, price = terms["qty"], terms["price"]
        order_type, stop = terms["order_type"], terms["stop"]
        if order_type == "market" and not broker.market_open():
            raise ValueError("Immediate market orders require an open regular session")
        condition = body.get("condition")
        if condition not in (None, "above", "below"):
            raise ValueError("Choose above or below")
        if not condition and body.get("threshold") is not None:
            raise ValueError("Threshold requires above/below condition")
        threshold = money(body.get("threshold")) if condition else None
        quote = broker.quote(symbol)
        reference = money(quote["ask"] if side == "buy" else quote["bid"])
        if asset == 'bitcoin' and terms['notional'] and terms['notional'] / reference < D(metadata['min_order_size']):
            raise ValueError('Notional violates broker minimum order size at the fresh quote')
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
        if order_type in ("stop", "stop_limit"):
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
        reserve_cash = (terms["notional"] or qty * price) * D("1.01") if side == "buy" else D(0)
        if side == "buy":
            if reserve_cash > 100:
                raise ValueError("$100 entry cap includes fee allowance")
            reserved = sum((D(r["reserved_cash"]) for r in reservations), D(0))
            if reserve_cash > self.spendable_cash(asset, account) - sum(
                (D(r["reserved_cash"]) for r in reservations if r["asset"] == asset), D(0)
            ):
                raise ValueError("Insufficient unreserved cash")
            if reserve_cash > D(account["cash"]) - reserved:
                raise ValueError("Insufficient broker cash for shared reservations")
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
            if qty > min(owned, self.attributed_qty(asset, symbol)) - reserved:
                raise ValueError(
                    "Cannot sell more than this StockWatch-owned sleeve quantity owns and has unreserved"
                )
        return {
            **body,
            "symbol": symbol,
            "qty": str(qty),
            "limit": str(price),
            "notional": str(terms["notional"]) if terms["notional"] else None,
            "order_type": order_type,
            "time_in_force": terms["time_in_force"],
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

    def state_revision(self):
        return self.db.execute("SELECT revision FROM state_revision WHERE id=1").fetchone()[0]

    def unchanged(self, revision):
        if self.state_revision() != revision:
            raise ValueError("Account state changed during validation; preview again")

    def preview(self, body, user, chat, request):
        if not request or len(request) > 160:
            raise ValueError("A stable request ID is required")
        state = self.state_revision()
        existing = self.db.execute("SELECT 1 FROM drafts WHERE request_id=?", (request,)).fetchone()
        preview = None if existing else self.validate(body)
        with transaction(self.db):
            self.unchanged(state)
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
        state = self.state_revision()
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
        with transaction(self.db):
            self.unchanged(state)
            if row["expires"] <= self.now():
                raise ValueError("Confirmation expired; preview again")
            if (
                body["action"] == "exit"
                and current["qty"] != document["preview"]["qty"]
            ):
                raise ValueError("Position changed; preview the exit again")
            if current["account_id"] != document["preview"]["account_id"]:
                raise ValueError("Account identity changed")
            if body["action"] == "setup" and current["broker_cash"] != document["preview"]["broker_cash"]:
                raise ValueError("Broker cash changed; preview account setup again")
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
                for sleeve in ("stocks", "bitcoin"):
                    self.db.execute(
                        "INSERT INTO accounts(asset,account_id,budget,entry_cap,confirmed_at,initial_cash) VALUES (?,?,?,?,?,?)",
                        (sleeve, current["account_id"], "1000", "100", now, current["broker_cash"]),
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
                    "time_in_force": current["time_in_force"],
                    "client_order_id": order,
                }
                if current.get("notional"):
                    request.pop("qty")
                    request["notional"] = current["notional"]
                if request["type"] in ("market", "stop"):
                    request.pop("limit_price")
                if body.get("order_type") in ("stop", "stop_limit"):
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
