"""Single-owner reconciliation. Unknown POST outcomes are looked up, never replaced."""

from decimal import Decimal as D
import json
from .store import TERMINAL, canonical, notify, transaction


def reconcile(manual, assets=("stocks", "bitcoin")):
    db = manual.db
    from .protection import manage

    if (
        "stocks" in assets
        and "stocks" in manual.brokers
        and hasattr(manual.brokers["stocks"], "batch_quotes")
    ):
        symbols = [
            r[0]
            for r in db.execute(
                "SELECT symbol FROM instructions WHERE asset='stocks' AND status IN ('intent','armed') UNION SELECT i.symbol FROM protective_plans p JOIN instructions i ON i.id=p.parent WHERE i.asset='stocks' AND p.status IN ('active','triggered')"
            )
        ]
        if symbols:
            try:
                manual.brokers["stocks"].batch_quotes(symbols)
            except Exception:
                manual.brokers["stocks"].quotes_cache = {
                    symbol: {"t": "1970-01-01T00:00:00Z", "ap": 1, "bp": 1}
                    for symbol in symbols
                }
    manage(manual, assets)
    for row in db.execute(
        "SELECT * FROM instructions WHERE status NOT IN ('filled','canceled','expired','rejected') ORDER BY created"
    ).fetchall():
        if row["asset"] not in assets:
            continue
        try:
            account = manual.account(row["asset"])
            if account["id"] != row["account_id"]:
                raise ValueError("Account identity changed")
            broker = manual.brokers[row["asset"]]
            now = manual.now()
            found = broker.lookup(row["id"])
            if found:
                qty = D(found.get("filled_qty") or "0")
                price = D(found.get("filled_avg_price") or "0")
                if qty < D(row["filled_qty"]) or qty > D(row["qty"]):
                    raise ValueError("Unexpected cumulative fill quantity")
                status = found["status"]
                if status not in (
                    *TERMINAL,
                    "new",
                    "accepted",
                    "partially_filled",
                    "pending_new",
                    "pending_cancel",
                    "pending_replace",
                    "accepted_for_bidding",
                    "done_for_day",
                    "stopped",
                    "suspended",
                    "calculated",
                ):
                    raise ValueError(
                        "Unrecognized broker status; reconciliation required"
                    )
                remaining = max(D(0), D(row["qty"]) - qty)
                with transaction(db):
                    db.execute(
                        "INSERT OR IGNORE INTO fills VALUES (?,?,?,?,?)",
                        (row["id"], str(qty), str(qty * price), now, canonical(found)),
                    ) if qty else None
                    db.execute(
                        """UPDATE instructions SET status=?,broker_id=?,filled_qty=?,filled_notional=?,response=?,reserved_cash=?,reserved_qty=?,updated=? WHERE id=?""",
                        (
                            status,
                            found["id"],
                            str(qty),
                            str(qty * price),
                            canonical(found),
                            str(
                                remaining * D(row["limit_price"]) * D("1.01")
                                if row["side"] == "buy" and status not in TERMINAL
                                else 0
                            ),
                            str(
                                remaining
                                if row["side"] == "sell" and status not in TERMINAL
                                else 0
                            ),
                            now,
                            row["id"],
                        ),
                    )
                    if qty != D(row["filled_qty"]) or status in TERMINAL:
                        db.execute(
                            "UPDATE outbox SET status='superseded' WHERE status='pending' AND id LIKE ?",
                            ("order:" + row["id"] + ":%",),
                        )
                        notify(
                            db,
                            f"order:{row['id']}:{status}:{qty}",
                            f"Manual {row['asset']} {row['symbol']} {row['side']}: {status}; filled {qty} at {price}",
                            now,
                        )
                if status not in TERMINAL and (
                    row["cancel_requested"]
                    or (
                        row["side"] == "buy"
                        and (row["expires"] is not None and now >= row["expires"])
                    )
                ):
                    broker.cancel(found["id"])
                continue
            # A missing lookup after an uncertain POST is NOT proof of rejection.
            # Retain the reservation and request operator reconciliation, never blindly retry.
            if row["status"] not in ("intent", "armed"):
                with db:
                    db.execute(
                        "UPDATE instructions SET status='uncertain',updated=? WHERE id=?",
                        (now, row["id"]),
                    )
                    notify(
                        db,
                        "uncertain:" + row["id"],
                        "Uncertain manual order "
                        + row["id"]
                        + "; reservation retained; reconcile at Alpaca before retrying.",
                        now,
                    )
                continue
            if row["cancel_requested"] or (
                row["expires"] is not None and now >= row["expires"]
            ):
                with db:
                    db.execute(
                        "UPDATE instructions SET status=?,reserved_cash='0',reserved_qty='0',updated=? WHERE id=?",
                        (
                            "canceled" if row["cancel_requested"] else "expired",
                            now,
                            row["id"],
                        ),
                    )
                continue
            if row["status"] not in ("intent", "armed"):
                continue
            if not broker.market_open():
                continue
            observation = manual.observation() if row["asset"] == "bitcoin" else None
            quote = broker.quote(row["symbol"])
            if row["condition"]:
                if row["asset"] == "bitcoin":
                    if not observation or not observation.get("fresh"):
                        continue
                    trigger = D(str(observation["price"]))
                else:
                    trigger = D(quote["ask"] if row["side"] == "buy" else quote["bid"])
                threshold = D(row["threshold"])
                if not (
                    trigger >= threshold
                    if row["condition"] == "above"
                    else trigger <= threshold
                ):
                    continue
            # Quotes validate protection immediately before submission, including recovery.
            if (
                row["side"] == "buy"
                and D(quote["ask"]) > D(row["limit_price"])
                and row["condition"]
            ):
                continue
            reservations = db.execute(
                "SELECT * FROM instructions WHERE account_id=? AND status NOT IN ('filled','canceled','expired','rejected')",
                (row["account_id"],),
            ).fetchall()
            known = {r["broker_id"] for r in reservations if r["broker_id"]}
            if any(order["id"] not in known for order in broker.open_orders()):
                raise ValueError("External order requires reconciliation")
            if row["side"] == "buy" and sum(
                (D(r["reserved_cash"]) for r in reservations), D(0)
            ) > min(D(account["cash"]), D(1000)):
                raise ValueError("Reserved cash exceeds available cash")
            if row["side"] == "sell":
                owned = sum(
                    (
                        D(p["qty"])
                        for p in broker.positions()
                        if p["symbol"].replace("/", "")
                        == row["symbol"].replace("/", "")
                    ),
                    D(0),
                )
                reserved = sum(
                    (
                        D(r["reserved_qty"])
                        for r in reservations
                        if r["symbol"] == row["symbol"]
                    ),
                    D(0),
                )
                if reserved > owned:
                    raise ValueError("Reserved quantity exceeds owned quantity")
            quote = broker.quote(row["symbol"])
            if (
                row["side"] == "buy"
                and row["condition"]
                and D(quote["ask"]) > D(row["limit_price"])
            ):
                continue
            if row["condition"] and row["asset"] == "bitcoin":
                observation = manual.observation()
                if not observation or not observation.get("fresh"):
                    continue
                trigger = D(str(observation["price"]))
                threshold = D(row["threshold"])
                if not (
                    trigger >= threshold
                    if row["condition"] == "above"
                    else trigger <= threshold
                ):
                    continue
            dispatch_at = manual.now()
            audit = json.loads(row["audit"])
            audit.update(
                {
                    "dispatch_quote": quote,
                    "dispatch_observation": observation,
                    "dispatch_at": dispatch_at,
                    "trigger_to_dispatch_ms": (dispatch_at - now) * 1000,
                }
            )
            if observation and observation.get("sourceAt"):
                from ..systems.engine import instant

                audit["source_event_age_ms"] = (
                    dispatch_at - instant(observation["sourceAt"]).timestamp()
                ) * 1000
                audit["receipt_to_dispatch_ms"] = (
                    dispatch_at * 1000 - observation["receivedAt"]
                )
            with transaction(db):
                current = db.execute(
                    "SELECT status,cancel_requested,expires FROM instructions WHERE id=?",
                    (row["id"],),
                ).fetchone()
                if (
                    current["status"] not in ("intent", "armed")
                    or current["cancel_requested"]
                    or (
                        current["expires"] is not None
                        and manual.now() >= current["expires"]
                    )
                ):
                    continue
                db.execute(
                    "UPDATE instructions SET status='submitting',audit=?,updated=? WHERE id=?",
                    (canonical(audit), now, row["id"]),
                )
            try:
                response = broker.submit_request(json.loads(row["request"]))
                audit["ack_at"] = manual.now()
                audit["broker_ack_ms"] = (audit["ack_at"] - dispatch_at) * 1000
                with db:
                    db.execute(
                        "UPDATE instructions SET broker_id=?,status=?,response=?,audit=?,updated=? WHERE id=?",
                        (
                            response["id"],
                            "submitting",
                            canonical(response),
                            canonical(audit),
                            manual.now(),
                            row["id"],
                        ),
                    )
            except Exception:
                with db:
                    db.execute(
                        "UPDATE instructions SET status='uncertain',updated=? WHERE id=?",
                        (manual.now(), row["id"]),
                    )
                    notify(
                        db,
                        "uncertain:" + row["id"],
                        "Uncertain manual order "
                        + row["id"]
                        + "; lookup required before any retry.",
                        manual.now(),
                    )
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO health VALUES ('execution',?,NULL)",
                    (manual.now(),),
                )
        except Exception as error:
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO health VALUES ('execution',?,?)",
                    (manual.now(), str(error)[:300]),
                )
