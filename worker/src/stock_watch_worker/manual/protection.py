"""Application-managed exits tied to actual entry fills; never broker-atomic OCO."""

from decimal import Decimal as D, ROUND_DOWN, ROUND_UP
import json
import uuid
from .store import canonical, money, transaction, TERMINAL, notify


def validate(manual, body, account):
    db = manual.db
    parent = db.execute(
        "SELECT * FROM instructions WHERE id=? AND account_id=? AND side='buy'",
        (body.get("instruction"), account["id"]),
    ).fetchone()
    if not parent:
        raise ValueError("Choose a buy instruction owned by this manual account")
    plan = db.execute(
        "SELECT * FROM protective_plans WHERE parent=? AND status!='closed' AND status!='canceled'",
        (parent["id"],),
    ).fetchone()
    if body["action"] == "cancel_plan":
        if not plan:
            raise ValueError("No active protective plan for this entry")
        return {
            **body,
            "account_id": account["id"],
            "plan": plan["id"],
            "symbol": parent["symbol"],
        }
    if plan:
        raise ValueError("Cancel the existing plan before changing its thresholds")
    stop = money(body["stop_loss"]) if body.get("stop_loss") is not None else None
    take = money(body["take_profit"]) if body.get("take_profit") is not None else None
    if stop is None and take is None:
        raise ValueError("Provide stop_loss, take_profit, or both")
    if stop and take and stop >= take:
        raise ValueError("Stop loss must be below take profit")
    if db.execute(
        "SELECT 1 FROM instructions WHERE account_id=? AND symbol=? AND id!=? AND (CAST(filled_qty AS REAL)>0 OR status NOT IN ('filled','canceled','expired','rejected'))",
        (account["id"], parent["symbol"], parent["id"]),
    ).fetchone():
        raise ValueError(
            "Protective plans require one isolated entry per symbol; other trades need reconciliation first"
        )
    if parent["status"] in TERMINAL and D(parent["filled_qty"]) == 0:
        raise ValueError("Entry closed without any fills")
    quote = manual.brokers[parent["asset"]].quote(parent["symbol"])
    observation = manual.observation() if parent["asset"] == "bitcoin" else None
    observed = (
        D(str(observation["price"]))
        if observation and observation.get("fresh")
        else D(quote["bid"])
        if parent["asset"] == "stocks"
        else None
    )
    satisfied = bool(
        observed is not None
        and ((stop and observed <= stop) or (take and observed >= take))
    )
    return {
        **body,
        "already_satisfied": satisfied,
        "quote": quote,
        "observation": observation,
        "account_id": account["id"],
        "symbol": parent["symbol"],
        "stop_loss": str(stop) if stop else None,
        "take_profit": str(take) if take else None,
        "quantity": "Actual fills only, resized after entry cancellation and broker reconciliation",
        "requires_online": True,
        "exit_limit_allowance": "0.5% below the fresh Alpaca bid; fills are not guaranteed",
        "expiry": "Until position closes or explicitly canceled",
        "oco": "Application managed, not broker atomic",
    }


def reserve(manual, plan):
    """Current fill entitlement reserved for the plan, separate from pending exits."""
    parent = manual.db.execute(
        "SELECT filled_qty,asset FROM instructions WHERE id=?", (plan["parent"],)
    ).fetchone()
    sold = sum(
        (
            D(row[0])
            for row in manual.db.execute(
                "SELECT filled_qty FROM instructions WHERE json_extract(audit,'$.protective_plan')=?",
                (plan["id"],),
            )
        ),
        D(0),
    )
    return max(D(0), D(parent["filled_qty"]) - D(str(sold)))


def manage(manual, assets):
    db = manual.db
    for plan in db.execute(
        "SELECT * FROM protective_plans WHERE status IN ('active','triggered','cancel_requested')"
    ).fetchall():
        parent = db.execute(
            "SELECT * FROM instructions WHERE id=?", (plan["parent"],)
        ).fetchone()
        if parent["asset"] not in assets:
            continue
        try:
            broker = manual.brokers[parent["asset"]]
            account = manual.account(parent["asset"])
            if account["id"] != parent["account_id"]:
                raise ValueError("Protective account identity changed")
            children = db.execute(
                "SELECT * FROM instructions WHERE json_extract(audit,'$.protective_plan')=?",
                (plan["id"],),
            ).fetchall()
            pending = [row for row in children if row["status"] not in TERMINAL]
            if plan["status"] == "cancel_requested":
                with db:
                    for row in pending:
                        db.execute(
                            "UPDATE instructions SET cancel_requested=1 WHERE id=?",
                            (row["id"],),
                        )
                    if not pending:
                        db.execute(
                            "UPDATE protective_plans SET status='canceled' WHERE id=?",
                            (plan["id"],),
                        )
                continue
            if pending:
                continue
            if D(parent["filled_qty"]) <= 0:
                if parent["status"] in TERMINAL:
                    with db:
                        db.execute(
                            "UPDATE protective_plans SET status='closed' WHERE id=?",
                            (plan["id"],),
                        )
                continue
            if not broker.market_open():
                continue
            positions = broker.positions()
            owned = sum(
                (
                    D(p["qty"])
                    for p in positions
                    if p["symbol"].replace("/", "") == parent["symbol"].replace("/", "")
                ),
                D(0),
            )
            entitlement = reserve(manual, plan)
            if owned <= 0 or entitlement <= 0:
                if parent["status"] in TERMINAL:
                    with db:
                        db.execute(
                            "UPDATE protective_plans SET status='closed' WHERE id=?",
                            (plan["id"],),
                        )
                continue
            quote = broker.quote(parent["symbol"])
            observation = manual.observation() if parent["asset"] == "bitcoin" else None
            if plan["status"] == "active":
                if parent["asset"] == "bitcoin" and (
                    not observation or not observation.get("fresh")
                ):
                    continue
                observed = (
                    D(str(observation["price"])) if observation else D(quote["bid"])
                )
                if not (
                    (plan["stop_loss"] and observed <= D(plan["stop_loss"]))
                    or (plan["take_profit"] and observed >= D(plan["take_profit"]))
                ):
                    continue
                with db:
                    db.execute(
                        "UPDATE protective_plans SET status='triggered' WHERE id=?",
                        (plan["id"],),
                    )
            # Wait for all entry fills/cancel acknowledgements before sizing an exit.
            if parent["status"] not in TERMINAL:
                with db:
                    db.execute(
                        "UPDATE instructions SET cancel_requested=1 WHERE id=?",
                        (parent["id"],),
                    )
                continue
            metadata = broker.metadata(parent["symbol"])
            increment = D(metadata.get("min_trade_increment") or "1")
            qty = (min(owned, entitlement) / increment).to_integral_value(
                rounding=ROUND_DOWN
            ) * increment
            if qty < D(metadata.get("min_order_size") or "1"):
                with db:
                    notify(
                        db,
                        "protection-dust:" + plan["id"],
                        "Protective residual below broker minimum; manual review required.",
                        manual.now(),
                    )
                continue
            limit = (D(quote["bid"]) * D(".995")).quantize(
                D(".01") if D(quote["bid"]) >= 1 else D(".0001"), rounding=ROUND_UP
            )
            if limit <= 0:
                raise ValueError("Protective limit must be positive")
            identifier = "protect-" + uuid.uuid4().hex
            request = {
                "client_order_id": identifier,
                "symbol": parent["symbol"],
                "side": "sell",
                "qty": str(qty),
                "type": "limit",
                "limit_price": str(limit),
                "time_in_force": "gtc",
            }
            with transaction(db):
                current = db.execute(
                    "SELECT status FROM protective_plans WHERE id=?", (plan["id"],)
                ).fetchone()
                if current["status"] != "triggered":
                    continue
                db.execute(
                    """INSERT INTO instructions(id,account_id,asset,symbol,side,qty,limit_price,expires,status,request,reserved_cash,reserved_qty,audit,created,updated)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        identifier,
                        parent["account_id"],
                        parent["asset"],
                        parent["symbol"],
                        "sell",
                        str(qty),
                        str(limit),
                        None,
                        "intent",
                        canonical(request),
                        "0",
                        str(qty),
                        canonical(
                            {
                                "protective_plan": plan["id"],
                                "parent": parent["id"],
                                "trigger_quote": quote,
                                "trigger_observation": observation,
                                "parent_attribution": json.loads(parent["audit"]),
                            }
                        ),
                        manual.now(),
                        manual.now(),
                    ),
                )
                notify(
                    db,
                    "protective:" + identifier,
                    "Protective paper exit queued for "
                    + parent["symbol"]
                    + "; limit "
                    + str(limit)
                    + "; not guaranteed to fill.",
                    manual.now(),
                )
        except Exception as error:
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO health VALUES ('protection',?,?)",
                    (manual.now(), str(error)[:300]),
                )
