"""Broker-reconciled account P&L, with durable observed fee activities."""

from datetime import datetime, timezone
from decimal import Decimal as D
from .store import canonical


def performance(manual, account_row, account, positions):
    db = manual.db
    broker = manual.brokers[account_row["asset"]]
    after = datetime.fromtimestamp(
        account_row["confirmed_at"], timezone.utc
    ).isoformat()
    fees = broker.fees(after)
    with db:
        for fee in fees:
            if not fee.get("id"):
                raise ValueError("Fee activity lacks stable identity")
            db.execute(
                "INSERT INTO fee_activities(account_id,id,payload,observed) VALUES (?,?,?,?) ON CONFLICT(account_id,id) DO UPDATE SET payload=excluded.payload,observed=excluded.observed",
                (account["id"], fee["id"], canonical(fee), manual.now()),
            )
    orders = db.execute(
        "SELECT * FROM instructions WHERE account_id=?", (account["id"],)
    ).fetchall()
    expected_cash = D(account_row["initial_cash"])
    expected = {}
    for order in orders:
        sign = 1 if order["side"] == "buy" else -1
        symbol = order["symbol"].replace("/", "")
        expected[symbol] = expected.get(symbol, D(0)) + sign * D(order["filled_qty"])
        expected_cash -= sign * D(order["filled_notional"])
    fee_cash = D(0)
    for fee in fees:
        fee_cash += D(str(fee.get("net_amount") or 0))
        if fee.get("qty"):
            symbol = str(fee.get("symbol", "")).replace("/", "")
            if symbol == "BTC":
                symbol = "BTCUSD"
            if not symbol:
                raise ValueError("Quantity fee lacks asset identity")
            expected[symbol] = expected.get(symbol, D(0)) - abs(D(str(fee["qty"])))
    expected_cash += fee_cash
    actual = {p["symbol"].replace("/", ""): D(p["qty"]) for p in positions}
    reconciled = abs(D(account["cash"]) - expected_cash) <= D(".02") and all(
        abs(expected.get(s, D(0)) - actual.get(s, D(0))) <= D(".00000001")
        for s in set(expected) | set(actual)
    )
    return {
        "account_id": account["id"],
        "asset": account_row["asset"],
        "cash_reconciled": reconciled,
        "broker_equity": account.get("equity"),
        "starting_cash": account_row["initial_cash"],
        "allocated_budget": account_row["budget"],
        "total_pnl": str(D(account["equity"]) - D(account_row["initial_cash"]))
        if reconciled and account.get("equity") is not None
        else None,
        "cash_fee_activities": str(fee_cash),
        "fee_activity_count": len(fees),
        "status": "Broker-reconciled total P&L including posted fees; late activities can revise it"
        if reconciled
        else "Unreconciled: external activity, corporate action, pending fill or fee posting; total P&L withheld",
    }
