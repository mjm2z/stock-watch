"""Decimal rollups invalidated by fill/fee changes, not every owner heartbeat."""
import json
from .model import money,canonical

def totals(db,account):
    cached=db.execute("SELECT 1 FROM sqlite_master WHERE name='btc_reconciliation_cache'").fetchone()
    revision=0
    if cached:
        row=db.execute('SELECT revision FROM btc_ledger_revisions WHERE account_id=?',(account,)).fetchone(); revision=row[0] if row else 0
        saved=db.execute('SELECT payload_json FROM btc_reconciliation_cache WHERE account_id=? AND revision=?',(account,revision)).fetchone()
        if saved: return {k:money(v) for k,v in json.loads(saved[0]).items()}
    result={k:money(0) for k in ('gross_qty','cash_delta','actual_qty','actual_cash','modeled_qty_fee','modeled_cash_fee')}
    for order in db.execute('SELECT * FROM btc_orders WHERE account_id=?',(account,)):
        buy=order['side']=='buy'; quantity=money(order['filled_qty']); notional=money(order['filled_notional'])
        result['gross_qty']+=quantity*(1 if buy else -1); result['cash_delta']+=notional*(-1 if buy else 1)
        result['modeled_qty_fee']+=money(order['fee_quantity_adjustment'])+(quantity*money('.0025') if buy else 0)
        result['modeled_cash_fee']+=money(order['fee_cash_adjustment'])+(notional*money('.0025') if not buy else 0)
    for row in db.execute('SELECT payload_json FROM btc_fees WHERE account_id=?',(account,)):
        fee=json.loads(row[0]); result['actual_cash']+=money(fee.get('net_amount') or 0)
        if str(fee.get('symbol','')).replace('/','') in ('BTC','BTCUSD'): result['actual_qty']+=abs(money(fee.get('qty') or 0))
    if cached:
        with db: db.execute('INSERT OR REPLACE INTO btc_reconciliation_cache VALUES (?,?,?)',(account,revision,canonical({k:str(v) for k,v in result.items()})))
    return result

def experimental_delta(db,account):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='experiment_orders'").fetchone(): return money(0),money(0),money(0),set()
    qty=cash=provision=money(0)
    for r in db.execute('SELECT side,filled_qty,filled_notional,id FROM experiment_orders WHERE account_id=?',(account,)):
        buy=r['side']=='buy'; qty+=money(r['filled_qty'])*(1 if buy else -1); cash+=money(r['filled_notional'])*(-1 if buy else 1)
        if buy and not db.execute('SELECT 1 FROM experiment_fees WHERE order_id=? AND applied=1',(r['id'],)).fetchone(): provision+=money(r['filled_qty'])*money('.0025')
    for r in db.execute('SELECT cash,quantity FROM experiment_fees WHERE account_id=? AND applied=1',(account,)):
        cash-=money(r['cash']); qty-=money(r['quantity'])
    known={r[0] for r in db.execute("SELECT broker_id FROM experiment_orders WHERE account_id=? AND broker_id IS NOT NULL AND status NOT IN ('filled','canceled','expired','rejected')",(account,))}
    return qty,cash,provision,known
