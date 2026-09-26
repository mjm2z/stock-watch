"""Auditable allocation of broker fees, including end-of-day aggregate fees.

Without an order link, divide a fee among that UTC day's matching credited-asset
fills in proportion to actual quantity (BTC) or proceeds (USD). Never allocate a
fee with missing fill history, unknown assets, or external orders.
"""
from datetime import timedelta
from decimal import Decimal
import json
from .engine import canonical, instant

D=Decimal
FEE=D('.0025')


def capture(db,broker,account,now):
    latest=db.execute('SELECT MAX(at) FROM btc_fills').fetchone()[0]
    after=max(instant(account['created_at']),instant(latest)-timedelta(days=3)).isoformat() if latest else account['created_at']
    for fill in broker.fills(after):
        order=db.execute('SELECT * FROM btc_orders WHERE broker_id=?',(fill['order_id'],)).fetchone()
        if not order or str(fill.get('symbol','')).replace('/','')!='BTCUSD' or fill['side']!=order['side']:
            raise ValueError('Unowned fill activity; account reconciliation required')
        qty=D(fill['qty']); price=D(fill['price'])
        if qty<=0 or price<=0: raise ValueError('Invalid fill activity')
        with db: db.execute('INSERT OR IGNORE INTO btc_fills VALUES (?,?,?,?,?)',(fill['id'],order['id'],instant(fill['transaction_time']).isoformat(),str(qty),str(qty*price)))
    latest=db.execute('SELECT MAX(captured_at) FROM btc_fees').fetchone()[0]
    after=max(instant(account['created_at']),instant(latest)-timedelta(days=3)).isoformat() if latest else account['created_at']
    for fee in broker.fees(after):
        with db: db.execute('INSERT OR IGNORE INTO btc_fees VALUES (?,?,NULL,?,\'unattributed\',?)',(fee['id'],account['id'],canonical(fee),now.isoformat()))
    # An incomplete fill activity feed cannot redistribute fees to wrong sleeves.
    complete=True
    for order in db.execute('SELECT * FROM btc_orders'):
        filled=sum((D(r[0]) for r in db.execute('SELECT quantity FROM btc_fills WHERE order_id=?',(order['id'],))),D(0))
        if abs(filled-D(order['filled_qty']))>D('.0000000001'): complete=False
    for row in db.execute("SELECT * FROM btc_fees WHERE status='unattributed'").fetchall():
        fee=json.loads(row['payload_json']); cash=-D(str(fee.get('net_amount') or 0)); qty=abs(D(str(fee.get('qty') or 0)))
        symbol=str(fee.get('symbol','')).replace('/','')
        if fee.get('status') not in (None,'executed') or cash<0 or (qty and symbol not in ('BTC','BTCUSD')) or (cash and qty): continue
        if not cash and not qty: continue
        side='buy' if qty else 'sell'; column='quantity' if qty else 'notional'
        order=db.execute('SELECT * FROM btc_orders WHERE broker_id=? AND side=?',(fee.get('order_id',''),side)).fetchone()
        if order:
            weights={order['id']:D(1)}; method='broker_order_id'
        elif complete and fee.get('date') and str(fee['date'])[:10]<now.date().isoformat():
            weights={}
            for fill in db.execute('''SELECT f.* FROM btc_fills f JOIN btc_orders o ON o.id=f.order_id
              WHERE substr(f.at,1,10)=? AND o.side=?''',(str(fee['date'])[:10],side)):
                weights[fill['order_id']]=weights.get(fill['order_id'],D(0))+D(fill[column])
            method='proportional_utc_day_'+column
        else: continue
        total=sum(weights.values(),D(0))
        if total<=0: continue
        remaining_cash,remaining_qty=cash,qty
        with db:
            ordered=sorted(weights.items())
            for i,(oid,weight) in enumerate(ordered):
                c=cash*weight/total if i<len(ordered)-1 else remaining_cash
                q=qty*weight/total if i<len(ordered)-1 else remaining_qty
                remaining_cash-=c; remaining_qty-=q
                db.execute('INSERT INTO btc_fee_allocations VALUES (?,?,?,?,?)',(row['id'],oid,str(c),str(q),method))
            db.execute("UPDATE btc_fees SET status='attributed',order_id=? WHERE id=?",(order['id'] if order else None,row['id']))


def reconcile_provisions(db,now,exact_account_match):
    """Charge higher actual fees immediately; release reserves after settlement."""
    for order in db.execute('SELECT * FROM btc_orders').fetchall():
        fees=db.execute('SELECT cash_fee,quantity_fee FROM btc_fee_allocations WHERE order_id=?',(order['id'],)).fetchall()
        if not fees: continue
        actual_cash=sum((D(f[0]) for f in fees),D(0)); actual_qty=sum((D(f[1]) for f in fees),D(0))
        provision_cash=D(order['filled_notional'])*FEE if order['side']=='sell' else D(0)
        provision_qty=D(order['filled_qty'])*FEE if order['side']=='buy' else D(0)
        settled=exact_account_match and order['status'] in ('filled','canceled','expired','rejected') and (now-instant(order['updated_at'])).total_seconds()>48*3600
        target_cash=actual_cash-provision_cash if settled else max(D(0),actual_cash-provision_cash)
        target_qty=actual_qty-provision_qty if settled else max(D(0),actual_qty-provision_qty)
        delta_cash=target_cash-D(order['fee_cash_adjustment']); delta_qty=target_qty-D(order['fee_quantity_adjustment'])
        if not delta_cash and not delta_qty: continue
        allocation=db.execute('SELECT * FROM btc_allocations WHERE version_id=?',(order['version_id'],)).fetchone()
        if not allocation: raise ValueError('Fee adjustment belongs to a retired allocation; reconcile before funding changes')
        cash=D(allocation['cash'])-delta_cash; qty=D(allocation['quantity'])-delta_qty
        with db:
            db.execute('UPDATE btc_allocations SET cash=?,quantity=?,exit_due_at=CASE WHEN exit_due_at IS NULL AND ?>0 THEN ? ELSE exit_due_at END WHERE version_id=?',
                       (str(cash),str(qty),float(qty),now.isoformat(),order['version_id']))
            db.execute('UPDATE btc_orders SET fee_cash_adjustment=?,fee_quantity_adjustment=? WHERE id=?',(str(target_cash),str(target_qty),order['id']))
