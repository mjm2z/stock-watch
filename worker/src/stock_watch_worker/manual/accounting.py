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
        "asset": "combined",
        "cash_reconciled": reconciled,
        "broker_equity": account.get("equity"),
        "starting_cash": account_row["initial_cash"],
        "allocated_budgets": {"stocks": "1000", "bitcoin": "1000"},
        "total_pnl": str(D(account["equity"]) - D(account_row["initial_cash"]))
        if reconciled and account.get("equity") is not None
        else None,
        "cash_fee_activities": str(fee_cash),
        "fee_activity_count": len(fees),
        "status": "Broker-reconciled total P&L including posted fees; late activities can revise it"
        if reconciled
        else "Unreconciled: external activity, corporate action, pending fill or fee posting; total P&L withheld",
    }


def allocation_performance(manual, account, positions, reconciled):
    """Prospective sleeve valuations. Never allocate an unidentified fee by guess."""
    rows = manual.db.execute('SELECT * FROM instructions WHERE account_id=?',(account['id'],)).fetchall()
    fees = [__import__('json').loads(r[0]) for r in manual.db.execute('SELECT payload FROM fee_activities WHERE account_id=?',(account['id'],))]
    reports = []
    for asset in ('stocks','bitcoin'):
        budget_row = manual.db.execute('SELECT budget FROM accounts WHERE asset=? AND account_id=?',(asset,account['id'])).fetchone()
        if not budget_row:
            continue
        budget = D(budget_row[0]); cash = budget; reason = None
        symbols = {r['symbol'].replace('/','') for r in rows if r['asset']==asset}
        for row in rows:
            if row['asset']==asset:
                cash -= (1 if row['side']=='buy' else -1)*D(row['filled_notional'])
        for fee in fees:
            symbol = str(fee.get('symbol') or '').replace('/','')
            if symbol == 'BTC': symbol = 'BTCUSD'
            amount = D(str(fee.get('net_amount') or 0))
            if amount and not symbol:
                reason = 'Posted fee lacks asset identity; allocation P&L withheld'
            elif symbol in symbols:
                cash += amount
        value = D(0)
        selected = []
        for position in positions:
            symbol = position['symbol'].replace('/','')
            if symbol not in symbols: continue
            try:
                mark = D(str(position['market_value']))
                if not mark.is_finite(): raise ValueError('Invalid valuation')
                value += mark
                selected.append({key:position.get(key) for key in ('symbol','qty','market_value','avg_entry_price','unrealized_pl')})
            except (KeyError, ValueError, __import__('decimal').InvalidOperation):
                reason = 'Broker position valuation unavailable'
        if not reconciled.get('cash_reconciled'):
            reason = 'Combined broker account does not reconcile'
        equity = cash+value
        reserved = sum((D(r['reserved_cash']) for r in rows if r['asset']==asset and r['status'] not in ('filled','canceled','expired','rejected')),D(0))
        reports.append({'asset':asset,'account_id':account['id'],'budget':str(budget),'currency':'USD',
            'cash':str(cash),'reserved_cash':str(reserved),'equity':None if reason else str(equity),
            'net_pnl':None if reason else str(equity-budget),'net_return':None if reason else float(equity/budget-1),
            'positions':selected,'as_of':manual.now(),'status':'unavailable' if reason else 'broker-paper allocation valuation',
            'unavailable_reason':reason,'methodology':'manual-allocation-v1; posted identifiable fees; unrealized marks from broker; late fees can revise',
            'benchmark':{'available':False,'reason':'Funding-matched benchmark and dividend treatment not established'}})
    return reports
