"""Reservations and cumulative-fill reconciliation with uncertain-order recovery."""
from datetime import timedelta
from decimal import ROUND_DOWN, ROUND_UP
import json
import uuid
from .model import TERMINAL, NY, canonical, digest, instant, stamp, money, exit_deadline, trade_session
from .store import transaction

def active(db,account=None):
    return db.execute("SELECT * FROM experiment_orders WHERE status NOT IN ('filled','canceled','expired','rejected') AND (? IS NULL OR account_id=?) ORDER BY CASE side WHEN 'sell' THEN 0 ELSE 1 END,created,id",(account,account)).fetchall()

def position(db,instance,symbol):
    return db.execute('SELECT * FROM experiment_positions WHERE instance_id=? AND symbol=?',(instance,symbol)).fetchone()

def session(db,now):
    return db.execute('SELECT * FROM experiment_calendar WHERE date=?',(now.astimezone(NY).date().isoformat(),)).fetchone()

def unsettled(db,instance):
    return sum((money(r[0]) for r in db.execute("SELECT f.notional FROM experiment_fills f JOIN experiment_orders o ON o.id=f.order_id WHERE o.instance_id=? AND o.side='sell' AND f.settled=0",(instance,))),money(0))

def available(db,instance):
    row=db.execute('SELECT cash FROM experiment_instances WHERE id=?',(instance,)).fetchone()
    reserved=sum((money(r[0]) for r in db.execute("SELECT reserved FROM experiment_orders WHERE instance_id=? AND status NOT IN ('filled','canceled','expired','rejected')",(instance,))),money(0))
    return money(row[0])-unsettled(db,instance)-reserved

def floor(value,step):
    return (money(value)/money(step)).to_integral_value(rounding=ROUND_DOWN)*money(step)

def sellable(db,instance,symbol,asset,now):
    row=position(db,instance,symbol)
    quantity=money(row['quantity']) if row else money(0)
    # Crypto positions already exclude credited-asset fee provisions. Counting
    # those reserves as positions would suppress subsequent intraday trials.
    return max(money(0),quantity)

def reserve(db,instance,symbol,side,q,metadata,now,reason,decision=None,market=False,parent=None,account_cash=None):
    row=db.execute('''SELECT i.*,b.account_id,b.asset,b.status batch_status,b.risk_reason,b.expires,b.state_revision,
        v.config_json FROM experiment_instances i JOIN experiment_batches b ON b.id=i.batch_id JOIN experiment_versions v ON v.id=i.version_id WHERE i.id=?''',(instance,)).fetchone()
    if not row: raise ValueError('Unknown experiment instance')
    cfg=json.loads(row['config_json']); revision=row['state_revision']
    if not trade_session(row['asset'],now,session(db,now)): raise ValueError('Waiting for regular session')
    if market and side!='sell': raise ValueError('Market fallback is exit-only')
    reference=money(q['ap'] if side=='buy' else q['bp']) if q else None
    if not market and reference is None: raise ValueError('Fresh quote required for limit')
    allowance=money(cfg['allowance'])
    if side=='buy':
        if money(q['ap'])/money(q['bp'])-1>money('.01'): raise ValueError('Quote spread exceeds one percent')
        limit=floor(reference*(1+allowance),metadata['price_increment'])
        if limit<reference: raise ValueError('Price increment exceeds entry allowance')
        # Entire fee-inclusive commitment, not just nominal order value, <= cap.
        cap=min(money(cfg['max_entry']),available(db,instance))
        qty=floor(cap/(limit*money('1.003')),metadata['quantity_increment'])
        reserved=qty*limit*money('1.003')
    else:
        limit=(reference*(1-allowance)/money(metadata['price_increment'])).to_integral_value(rounding=ROUND_UP)*money(metadata['price_increment']) if reference else None
        qty=floor(sellable(db,instance,symbol,row['asset'],now),metadata['quantity_increment']); reserved=money(0)
    if qty<money(metadata['minimum_quantity']): raise ValueError('Insufficient cash or quantity for broker minimum')
    identifier='exp-'+uuid.uuid4().hex
    request=dict(client_order_id=identifier,symbol=symbol,side=side,qty=str(qty),type='market' if market else 'limit',time_in_force='day' if row['asset']=='stocks' else 'gtc')
    if not market: request['limit_price']=str(limit)
    with transaction(db):
        latest=db.execute('SELECT state_revision FROM experiment_batches WHERE id=?',(row['batch_id'],)).fetchone()[0]
        if latest!=revision: raise ValueError('Execution state changed; evaluate again')
        if active_symbol(db,row['account_id'],symbol): raise ValueError('Another order owns this account/symbol')
        if legacy_pending_symbol(db,row['asset'],symbol): raise ValueError('A baseline order owns this symbol')
        if side=='buy':
            if row['batch_status']!='active' or row['paused'] or row['exit_requested'] or row['risk_reason'] or now>=instant(row['expires']):
                raise ValueError('New entries are paused or expired')
            own=position(db,instance,symbol)
            if own and money(own['quantity'])>=money(metadata['minimum_quantity']): raise ValueError('Adding to positions is disabled')
            if own and own['cooldown_until'] and now<instant(own['cooldown_until']): raise ValueError('Symbol cooldown')
            occupied=sum(money(r[0])>=money(metadata['minimum_quantity']) for r in db.execute('SELECT quantity FROM experiment_positions WHERE instance_id=?',(instance,)))
            pending=db.execute("SELECT COUNT(*) FROM experiment_orders WHERE instance_id=? AND side='buy' AND status NOT IN ('filled','canceled','expired','rejected')",(instance,)).fetchone()[0]
            if occupied+pending>=cfg['max_positions']: raise ValueError('Position capacity reached')
            day=now.astimezone(NY).date()
            entries=sum(1 for r in db.execute("SELECT created FROM experiment_orders WHERE instance_id=? AND side='buy' AND (status NOT IN ('rejected','canceled','expired') OR CAST(filled_qty AS REAL)>0)",(instance,)) if instant(r[0]).astimezone(NY).date()==day)
            if entries>=(1 if cfg['family']=='control' else cfg['entries_per_day']): raise ValueError('Daily entry limit reached')
            if available(db,instance)<reserved: raise ValueError('Waiting for settled cash')
            all_reserved=sum((money(o['reserved']) for o in active(db,row['account_id'])),money(0))
            if account_cash is None or money(account_cash)-all_reserved-legacy_reserved(db,row['asset'])<reserved:
                raise ValueError('Account-wide cash capacity unavailable')
        db.execute('''INSERT INTO experiment_orders(id,instance_id,account_id,symbol,side,decision_id,request_json,status,created,updated,expires,reserved,reason,parent_id,reserve_evidence_json)
            VALUES (?,?,?,?,?,?,?,'reserved',?,?,?,?,?,?,?)''',
            (identifier,instance,row['account_id'],symbol,side,decision,canonical(request),stamp(now),stamp(now),stamp(now+timedelta(seconds=60)),str(reserved),reason,parent,
             canonical({'quote':q,'metadata':metadata,'account_cash':str(account_cash) if account_cash is not None else None,'state_revision':revision})))
        db.execute('UPDATE experiment_batches SET state_revision=state_revision+1 WHERE id=?',(row['batch_id'],))
    return identifier

def active_symbol(db,account,symbol):
    return db.execute("SELECT 1 FROM experiment_orders WHERE account_id=? AND symbol=? AND status NOT IN ('filled','canceled','expired','rejected')",(account,symbol)).fetchone() is not None

def legacy_pending_symbol(db,asset,symbol):
    if asset=='bitcoin':
        return db.execute("SELECT 1 FROM btc_orders WHERE status NOT IN ('filled','canceled','expired','rejected') LIMIT 1").fetchone() is not None
    return db.execute("""SELECT 1 FROM paper_orders o JOIN signals s ON s.id=o.signal_id JOIN instruments i ON i.id=s.instrument_id
        WHERE i.symbol=? AND o.status IN ('pending','submitted','accepted','partially_filled') UNION ALL
        SELECT 1 FROM paper_exit_orders o JOIN paper_trade_lots l ON l.id=o.lot_id JOIN instruments i ON i.id=l.instrument_id
        WHERE i.symbol=? AND o.status IN ('pending','submitted','accepted','partially_filled') UNION ALL
        SELECT 1 FROM system_orders WHERE symbol=? AND status NOT IN ('filled','canceled','expired','rejected') LIMIT 1""",(symbol,symbol,symbol)).fetchone() is not None

def legacy_reserved(db,asset):
    if asset=='bitcoin':
        return sum((money(r[0]) for r in db.execute("SELECT reserved_cash FROM btc_orders WHERE status NOT IN ('filled','canceled','expired','rejected')")),money(0))
    value=sum((money(r[0]) for r in db.execute("SELECT notional_usd FROM paper_orders WHERE status IN ('pending','submitted','accepted','partially_filled')")),money(0))
    for r in db.execute("SELECT request_json FROM system_orders WHERE side='buy' AND status NOT IN ('filled','canceled','expired','rejected')"):
        value+=money(json.loads(r[0]).get('notional',0))
    return value

def apply_response(db,identifier,response,now):
    row=db.execute('SELECT * FROM experiment_orders WHERE id=?',(identifier,)).fetchone()
    if response.get('client_order_id')!=identifier or response.get('side')!=row['side'] or str(response.get('symbol','')).replace('/','')!=row['symbol'].replace('/',''):
        raise ValueError('Broker order identity mismatch')
    qty=money(response.get('filled_qty') or 0); notional=qty*money(response.get('filled_avg_price') or 0)
    if qty<money(row['filled_qty']) or notional<money(row['filled_notional']): raise ValueError('Broker cumulative fill regressed')
    if qty>money(json.loads(row['request_json'])['qty']): raise ValueError('Broker overfilled owned quantity')
    status=response.get('status','unknown')
    request=json.loads(row['request_json'])
    if response.get('qty') is not None and money(response['qty'])!=money(request['qty']): raise ValueError('Broker order quantity changed')
    if status=='filled' and qty!=money(request['qty']): raise ValueError('Incomplete fill marked filled')
    if status in ('done_for_day','replaced','suspended','stopped','calculated'): status='uncertain'
    at=stamp(now); dq=qty-money(row['filled_qty']); dn=notional-money(row['filled_notional'])
    with transaction(db):
        current=db.execute('SELECT * FROM experiment_orders WHERE id=?',(identifier,)).fetchone()
        if current['filled_qty']!=row['filled_qty'] or current['status']!=row['status']: raise ValueError('Concurrent fill update')
        instance=db.execute('''SELECT i.*,b.asset,b.plan_json,v.config_json FROM experiment_instances i JOIN experiment_batches b ON b.id=i.batch_id JOIN experiment_versions v ON v.id=i.version_id WHERE i.id=?''',(row['instance_id'],)).fetchone()
        cfg=json.loads(instance['config_json'])
        if dq>0:
            if dn<=0: raise ValueError('Fill price unavailable')
            p=position(db,row['instance_id'],row['symbol'])
            pq=money(p['quantity']) if p else money(0); cost=money(p['cost']) if p else money(0); realized=money(p['realized']) if p else money(0)
            if row['side']=='sell' and dq>pq: raise ValueError('Fill exceeds instance-owned quantity')
            when=instant(response.get('filled_at') or response.get('updated_at') or at)
            cal=session(db,when)
            settlement=cal['settlement_date'] if cal and instance['asset']=='stocks' else None
            filled_id=digest({'order':identifier,'quantity':str(qty),'notional':str(notional)})
            db.execute('INSERT INTO experiment_fills VALUES (?,?,?,?,?,?,?)',(filled_id,identifier,stamp(when),str(dq),str(dn),settlement,int(row['side']=='buy' or instance['asset']=='bitcoin')))
            fee=money('.0025') if instance['asset']=='bitcoin' else money(0)
            cash=money(instance['cash'])+(dn*(1-fee) if row['side']=='sell' else -dn)
            if row['side']=='buy':
                minimum=money(json.loads(instance['plan_json'])['preflight']['metadata'][row['symbol']]['minimum_quantity'])
                newq=pq+dq*(1-fee); cost+=dn; entered=p['entered'] if pq>=minimum else stamp(when)
                due=p['exit_due'] if pq>=minimum else stamp(exit_deadline(cfg,when,cal))
                cooldown=p['cooldown_until'] if p else None
            else:
                newq=pq-dq; removed=cost*dq/pq; cost-=removed; realized+=dn-removed
                entered=p['entered']; due=p['exit_due']; cooldown=stamp(now+timedelta(minutes=cfg['cooldown_minutes']))
            db.execute('''INSERT INTO experiment_positions VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(instance_id,symbol) DO UPDATE SET
                quantity=excluded.quantity,cost=excluded.cost,entered=excluded.entered,exit_due=excluded.exit_due,cooldown_until=excluded.cooldown_until,realized=excluded.realized''',
                (row['instance_id'],row['symbol'],str(newq),str(cost),entered,due,cooldown,str(realized)))
            db.execute('UPDATE experiment_instances SET cash=? WHERE id=?',(str(cash),row['instance_id']))
        remaining=money(0) if status in TERMINAL else max(money(0),money(row['reserved'])-dn)
        db.execute('UPDATE experiment_orders SET status=?,broker_id=?,updated=?,reserved=?,filled_qty=?,filled_notional=?,response_json=?,error=NULL WHERE id=?',
            (status,response['id'],at,str(remaining),str(qty),str(notional),canonical(response),identifier))
        db.execute('UPDATE experiment_batches SET state_revision=state_revision+1 WHERE id=?',(instance['batch_id'],))

def sync(db,broker,row,now,can_submit=True,force_cancel=False):
    """Never infer a failed POST from a later 404; uncertain orders stay reserved."""
    try:
        found=broker.lookup(row['id'])
        if found:
            apply_response(db,row['id'],found,now)
            if found.get('status') not in TERMINAL and (now>=instant(row['expires']) or force_cancel):
                with db: db.execute("UPDATE experiment_orders SET status='cancel_pending' WHERE id=?",(row['id'],))
                broker.cancel(found['id'])
                # A DELETE acknowledgement is not evidence that no fill raced it.
                final=broker.lookup(row['id'])
                if final: apply_response(db,row['id'],final,now)
            return
        if row['status']!='reserved':
            raise ValueError('Submission uncertain; awaiting broker client-ID reconciliation')
        if force_cancel:
            with db: db.execute("UPDATE experiment_orders SET status='canceled',reserved='0',updated=? WHERE id=?",(stamp(now),row['id']))
            return
        if now>=instant(row['expires']):
            with db: db.execute("UPDATE experiment_orders SET status='expired',reserved='0',updated=? WHERE id=?",(stamp(now),row['id']))
            return
        if not can_submit: return
        request=json.loads(row['request_json'])
        checked,account=broker.execution_check(request,row['account_id'])
        if checked>=instant(row['expires']): return
        if row['side']=='buy' and row['decision_id']:
            decision=db.execute('''SELECT d.cutoff,v.family FROM experiment_decisions d JOIN experiment_instances i ON i.id=d.instance_id
                JOIN experiment_versions v ON v.id=i.version_id WHERE d.id=?''',(row['decision_id'],)).fetchone()
            window=300 if decision['family']=='control' else 25
            if checked>instant(decision['cutoff'])+timedelta(seconds=window):
                with db: db.execute("UPDATE experiment_orders SET status='expired',reserved='0',error='Missed submission window' WHERE id=? AND status='reserved'",(row['id'],))
                return
        # Durable transition BEFORE network; a crash cannot issue a second POST.
        with transaction(db):
            owner=db.execute('''SELECT i.paused,i.exit_requested,b.status,b.risk_reason,b.expires FROM experiment_instances i
                JOIN experiment_batches b ON b.id=i.batch_id WHERE i.id=?''',(row['instance_id'],)).fetchone()
            if row['side']=='buy':
                if owner['paused'] or owner['exit_requested'] or owner['risk_reason'] or owner['status']!='active' or checked>=instant(owner['expires']):
                    db.execute("UPDATE experiment_orders SET status='canceled',reserved='0' WHERE id=? AND status='reserved'",(row['id'],))
                    return
                total=sum((money(o['reserved']) for o in active(db,row['account_id'])),money(0))
                if money(account['cash'])-legacy_reserved(db,broker.asset)<total: raise ValueError('Account cash changed before submission')
            changed=db.execute("UPDATE experiment_orders SET status='submitting',updated=? WHERE id=? AND status='reserved'",(stamp(now),row['id'])).rowcount
        if changed:
            found=broker.submit(request)
            apply_response(db,row['id'],found,now)
    except Exception as error:
        from ..http import ProviderError
        if isinstance(error,ProviderError) and error.status in (400,403,422) and db.execute('SELECT status FROM experiment_orders WHERE id=?',(row['id'],)).fetchone()[0]=='submitting':
            with db: db.execute("UPDATE experiment_orders SET status='rejected',reserved='0' WHERE id=?",(row['id'],))
        with db:
            db.execute('UPDATE experiment_orders SET error=?,updated=? WHERE id=?',(str(error)[:500],stamp(now),row['id']))
            status=db.execute('SELECT status FROM experiment_orders WHERE id=?',(row['id'],)).fetchone()[0]
            if row['error']!=str(error)[:500] and status in ('submitting','cancel_pending','uncertain','rejected'):
                from ..systems.research import audit
                audit(db,'experiment_order_rejected' if status=='rejected' else 'experiment_order_uncertain',row['id'],
                    {'symbol':row['symbol'],'side':row['side'],'reason':str(error)[:300],'status':status})

def release_settlement(db,now):
    with transaction(db):
        # Refresh missing dates if broker calendar evidence subsequently arrives.
        rows=db.execute("SELECT f.*,o.instance_id FROM experiment_fills f JOIN experiment_orders o ON o.id=f.order_id WHERE f.settled=0").fetchall()
        for row in rows:
            settlement=row['settlement_date']
            if not settlement:
                cal=session(db,instant(row['at'])); settlement=cal['settlement_date'] if cal else None
            settled=bool(settlement and now.astimezone(NY).date().isoformat()>=settlement)
            db.execute('UPDATE experiment_fills SET settlement_date=?,settled=? WHERE id=?',(settlement,int(settled),row['id']))
