"""Attribute broker fees by explicit order, or complete credited-asset day fills."""
from datetime import timedelta
import json
from .model import canonical, digest, instant, stamp, money
from .store import transaction

def capture(db,broker,batch,now):
    latest=db.execute('SELECT MAX(observed) FROM experiment_fee_receipts WHERE account_id=?',(batch['account_id'],)).fetchone()[0]
    after=max(instant(batch['created'])-timedelta(days=1),instant(latest)-timedelta(days=3)) if latest else instant(batch['created'])-timedelta(days=1)
    # A failure or pagination limit commits no incomplete feed snapshot.
    activities=broker.activities(stamp(after))
    with transaction(db):
        for item in activities:
            kind=item.get('activity_type')
            if kind=='FILL':
                qty=money(item['qty']); notional=qty*money(item['price'])
                if qty<=0 or notional<=0: raise ValueError('Invalid fill activity')
                db.execute('INSERT OR IGNORE INTO experiment_broker_fills VALUES (?,?,?,?,?,?,?)',
                    (batch['account_id'],item['id'],item['order_id'],stamp(instant(item['transaction_time'])),item['side'],str(qty),str(notional)))
            elif kind in ('CFEE','FEE'):
                db.execute('INSERT OR IGNORE INTO experiment_fee_receipts VALUES (?,?,?,?,0)',
                    (batch['account_id'],item['id'],canonical(item),stamp(now)))
    for receipt in db.execute('SELECT * FROM experiment_fee_receipts WHERE account_id=? AND applied=0',(batch['account_id'],)).fetchall():
        fee=json.loads(receipt['payload_json']); cash=-money(fee.get('net_amount') or 0); qty=abs(money(fee.get('qty') or 0))
        if cash<0 or (cash and qty) or (qty and str(fee.get('symbol','')).replace('/','') not in ('BTC','BTCUSD')) or fee.get('status') not in (None,'executed'): continue
        if not cash and not qty:
            with db: db.execute('UPDATE experiment_fee_receipts SET applied=1 WHERE account_id=? AND id=?',(batch['account_id'],receipt['id']))
            continue
        side='buy' if qty else 'sell'; weights={}; orders={}
        if fee.get('order_id'):
            weights[fee['order_id']]=money(1)
        elif fee.get('date') and str(fee['date'])[:10]<now.date().isoformat():
            for fill in db.execute('SELECT * FROM experiment_broker_fills WHERE account_id=? AND substr(at,1,10)=? AND side=?',(batch['account_id'],str(fee['date'])[:10],side)):
                weights[fill['broker_order_id']]=weights.get(fill['broker_order_id'],money(0))+money(fill['quantity'] if qty else fill['notional'])
        if not weights: continue
        valid=True
        for broker_id in weights:
            order=db.execute('SELECT * FROM experiment_orders WHERE account_id=? AND broker_id=? AND side=?',(batch['account_id'],broker_id,side)).fetchone()
            ledger='experiment'
            if not order:
                order=db.execute('SELECT * FROM btc_orders WHERE account_id=? AND broker_id=? AND side=?',(batch['account_id'],broker_id,side)).fetchone(); ledger='bitcoin'
            if not order: valid=False; break
            observed=sum((money(r[0]) for r in db.execute('SELECT quantity FROM experiment_broker_fills WHERE account_id=? AND broker_order_id=?',(batch['account_id'],broker_id))),money(0))
            if abs(observed-money(order['filled_qty']))>money('.0000000001'): valid=False; break
            orders[broker_id]=(ledger,order)
        if not valid: continue
        # Every filled order for the fee's day must have complete activity history,
        # including orders omitted by an incomplete/late upstream FILL feed.
        day=str(fee.get('date',''))[:10]
        if not fee.get('order_id'):
            for row in db.execute("""SELECT o.broker_id FROM experiment_orders o WHERE o.account_id=? AND o.side=? AND substr(o.updated,1,10)=? AND CAST(o.filled_qty AS REAL)>0
                UNION ALL SELECT o.broker_id FROM btc_orders o WHERE o.account_id=? AND o.side=? AND substr(o.updated_at,1,10)=? AND CAST(o.filled_qty AS REAL)>0""",
                (batch['account_id'],side,day,batch['account_id'],side,day)):
                if row['broker_id'] not in weights: valid=False
        if not valid: continue
        total=sum(weights.values(),money(0)); remaining_cash=cash; remaining_qty=qty
        with transaction(db):
            for index,broker_id in enumerate(sorted(weights)):
                c=cash*weights[broker_id]/total if index<len(weights)-1 else remaining_cash
                q=qty*weights[broker_id]/total if index<len(weights)-1 else remaining_qty
                remaining_cash-=c; remaining_qty-=q
                ledger,order=orders[broker_id]; key=digest({'fee':receipt['id'],'order':broker_id})
                payload={**fee,'attribution':'broker_order_id' if fee.get('order_id') else 'proportional_complete_utc_day','original_activity_id':receipt['id'],'order_id':broker_id,'net_amount':str(-c),'qty':str(q)}
                if ledger=='bitcoin':
                    db.execute("INSERT OR IGNORE INTO btc_fees VALUES (?,?,?,?,'attributed',?)",(key,batch['account_id'],order['id'],canonical(payload),stamp(now)))
                    db.execute('INSERT OR IGNORE INTO btc_fee_allocations VALUES (?,?,?,?,?)',(key,order['id'],str(c),str(q),payload['attribution']))
                else:
                    db.execute('INSERT INTO experiment_fees VALUES (?,?,?,?,?,?,?,1)',(key,batch['account_id'],order['id'],str(fee.get('date') or stamp(now)),str(c),str(q),canonical(payload)))
            db.execute('UPDATE experiment_fee_receipts SET applied=1 WHERE account_id=? AND id=?',(batch['account_id'],receipt['id']))
    reconcile_provisions(db,batch,now)
    return not db.execute('SELECT 1 FROM experiment_fee_receipts WHERE account_id=? AND applied=0',(batch['account_id'],)).fetchone()

def reconcile_provisions(db,batch,now,settled=False):
    """Charge higher fees now; release conservative reserves only after 48h and exact reconciliation."""
    for order in db.execute('SELECT * FROM experiment_orders WHERE account_id=? AND CAST(filled_qty AS REAL)>0',(batch['account_id'],)).fetchall():
        actual=db.execute('SELECT cash,quantity FROM experiment_fees WHERE order_id=? AND applied=1',(order['id'],)).fetchall()
        cash=sum((money(f['cash']) for f in actual),money(0)); qty=sum((money(f['quantity']) for f in actual),money(0))
        crypto=batch['asset']=='bitcoin'
        provision_q=money(order['filled_qty'])*money('.0025') if crypto and order['side']=='buy' else money(0)
        provision_c=money(order['filled_notional'])*money('.0025') if crypto and order['side']=='sell' else money(0)
        already_released=money(order['qty_fee_adjustment'])<0 or money(order['cash_fee_adjustment'])<0
        release=already_released or (settled and order['status'] in ('filled','canceled','expired','rejected') and now-instant(order['updated'])>=timedelta(hours=48))
        target_q=qty-provision_q if release else max(money(0),qty-provision_q)
        target_c=cash-provision_c if release else max(money(0),cash-provision_c)
        delta_q=target_q-money(order['qty_fee_adjustment']); delta_c=target_c-money(order['cash_fee_adjustment'])
        if delta_q==delta_c==0: continue
        with transaction(db):
            own=db.execute('SELECT * FROM experiment_positions WHERE instance_id=? AND symbol=?',(order['instance_id'],order['symbol'])).fetchone()
            if delta_q and (not own or money(own['quantity'])<delta_q): raise ValueError('Fee exceeds instance ownership')
            if delta_q: db.execute('UPDATE experiment_positions SET quantity=? WHERE instance_id=? AND symbol=?',(str(money(own['quantity'])-delta_q),order['instance_id'],order['symbol']))
            local=db.execute('SELECT cash FROM experiment_instances WHERE id=?',(order['instance_id'],)).fetchone()
            db.execute('UPDATE experiment_instances SET cash=? WHERE id=?',(str(money(local[0])-delta_c),order['instance_id']))
            db.execute('UPDATE experiment_orders SET qty_fee_adjustment=?,cash_fee_adjustment=? WHERE id=?',(str(target_q),str(target_c),order['id']))
