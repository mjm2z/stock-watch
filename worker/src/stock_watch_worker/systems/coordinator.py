"""Single Bitcoin paper-account owner; durable intents and per-version ledgers.

Cash and BTC fee provisions are conservative until broker activities arrive.
Unattributed activities or external activity block entries, never owned exits.
"""
from datetime import timedelta
from decimal import Decimal
import json
import uuid
from .automation_data import health
from .broker import rounded_quantity
from .engine import canonical, decision, instant
from .evaluation import config_for, forward_ready
from .history import latest_bars
from .research import audit
from .timeframes import deadline

D=Decimal
FEE=D('.0025')
TERMINAL=('filled','canceled','expired','rejected')


def active_orders(db,version=None):
    query="SELECT * FROM btc_orders WHERE status NOT IN ('filled','canceled','expired','rejected')"
    return db.execute(query+(' AND version_id=?' if version else ''),(version,) if version else ()).fetchall()


def eligible(db,version,now):
    row=db.execute('''SELECT q.status,q.evaluation_id,e.expires_at,e.budget,n.approved_at,n.paused,n.active
      FROM btc_qualifications q JOIN btc_evaluations e ON e.id=q.evaluation_id
      JOIN btc_enrollments n ON n.version_id=q.version_id WHERE q.version_id=?''',(version,)).fetchone()
    if not row or row['status']!='qualified' or not row['approved_at'] or row['paused'] or not row['active'] or instant(row['expires_at'])<=now: return None
    allocation=db.execute('SELECT budget,started_at FROM btc_allocations WHERE version_id=?',(version,)).fetchone()
    if allocation and not allocation['started_at']: return None
    if allocation and D(allocation[0])!=D(row['budget']): return None
    return row['evaluation_id'] if forward_ready(db,version,now)[0] else None


def fund(db,broker,versions,now):
    if not 1<=len(versions)<=5 or len(set(versions))!=len(versions): raise ValueError('Select one to five distinct versions')
    for version in versions:
        config_for(db,version)
        if not db.execute('SELECT 1 FROM btc_enrollments WHERE version_id=? AND active=1 AND approved_at IS NOT NULL',(version,)).fetchone(): raise ValueError('Approve each version before funding')
    if db.execute("SELECT 1 FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE v.asset='bitcoin' AND d.account_id IS NOT NULL").fetchone():
        raise ValueError('Legacy Bitcoin account ownership must be explicitly retired before shared funding')
    account=broker.account()
    if broker.positions() or broker.open_orders() or active_orders(db): raise ValueError('Funding changes require settled orders and a flat account')
    old=db.execute('SELECT * FROM btc_accounts').fetchone()
    if old and old['id']!=account['id']: raise ValueError('Paper account identity changed')
    if old and old['risk_paused']: raise ValueError('Reactivate the risk-paused account before changing allocations')
    if not old and abs(D(account['cash'])-D(300))>D('.01'): raise ValueError('Initial funding requires an empty separate $300 paper account')
    if old and abs(D(account['cash'])-(D(old['cash'])+sum((D(r['cash']) for r in db.execute('SELECT cash FROM btc_allocations')),D(0))))>D('.01'):
        raise ValueError('Reconcile settled cash and fees before changing allocations')
    total=min(D(300),D(account['cash'])); budget=(total/D(len(versions))).quantize(D('.00000001'))
    with db:
        if not old: db.execute('INSERT INTO btc_accounts(id,created_at) VALUES (?,?)',(account['id'],now.isoformat()))
        db.execute('DELETE FROM btc_allocations')
        for version in versions:
            db.execute('INSERT INTO btc_allocations(version_id,account_id,budget,cash,high_water,approved_at) VALUES (?,?,?,?,?,?)',
                       (version,account['id'],str(budget),str(budget),str(budget),now.isoformat()))
            db.execute("UPDATE btc_evaluations SET status='canceled' WHERE version_id=? AND status IN ('queued','running') AND CAST(budget AS REAL)!=?",(version,float(budget)))
            db.execute("UPDATE btc_qualifications SET status='collecting',reason='Funding changed; next scheduled review must use the new budget' WHERE version_id=? AND (evaluation_id IS NULL OR evaluation_id IN (SELECT id FROM btc_evaluations WHERE CAST(budget AS REAL)!=?))",(version,float(budget)))
        db.execute('UPDATE btc_accounts SET cash=? WHERE id=?',(str(D(account['cash'])-budget*len(versions)),account['id']))
        audit(db,'bitcoin_funding',account['id'],{'versions':versions,'each':str(budget),'total':str(total)})


def reserve(db,version,side,qty,price,now,evaluation,reason):
    identifier='btc2-'+uuid.uuid4().hex
    qty,price=D(str(qty)),D(str(price))
    if qty<=0 or price<=0 or not qty.is_finite() or not price.is_finite(): raise ValueError('Invalid order amount')
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT * FROM btc_allocations WHERE version_id=?',(version,)).fetchone()
        if not row or active_orders(db,version): raise ValueError('One outstanding intent per allocation')
        reserve_cash=qty*price*D('1.01') if side=='buy' else D(0)
        if side=='buy':
            account=db.execute('SELECT * FROM btc_accounts WHERE id=?',(row['account_id'],)).fetchone()
            if row['risk_paused'] or account['risk_paused'] or eligible(db,version,now)!=evaluation or not evaluation:
                raise ValueError('Entry is not qualified and approved')
            if reserve_cash>D(row['cash']): raise ValueError('Insufficient sleeve cash')
        elif side!='sell' or qty>D(row['quantity']): raise ValueError('Cannot sell another allocation’s Bitcoin')
        db.execute('''INSERT INTO btc_orders(id,version_id,account_id,side,quantity,reserved_cash,reference_price,created_at,updated_at,evaluation_id,reason)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(identifier,version,row['account_id'],side,str(qty),str(reserve_cash),str(price),now.isoformat(),now.isoformat(),evaluation,reason))
        audit(db,'bitcoin_order_intent',identifier,{'version':version,'evaluation':evaluation,'side':side,'quantity':str(qty),'reason':reason})
        db.commit()
    except Exception: db.rollback(); raise
    return identifier


def apply_fill(db,row,found,now):
    qty=D(found.get('filled_qty') or '0'); price=D(found.get('filled_avg_price') or '0')
    notional=qty*price; delta=qty-D(row['filled_qty']); money=notional-D(row['filled_notional'])
    if delta<0 or money<0: raise ValueError('Broker cumulative fills moved backwards')
    with db:
        allocation=db.execute('SELECT * FROM btc_allocations WHERE version_id=?',(row['version_id'],)).fetchone()
        cash=D(allocation['cash']); owned=D(allocation['quantity'])
        entry=allocation['entry_at']; due=allocation['exit_due_at']; entry_price=allocation['entry_price']
        if row['side']=='buy':
            if delta:entry_price=str((D(entry_price or price)*owned+money)/(owned+delta))
            cash-=money; owned+=delta*(1-FEE)
            if delta and not entry:
                # Use first reported fill timestamp, conservatively no later than observation.
                at=min(now,instant(found.get('filled_at') or now.isoformat()))
                config=config_for(db,row['version_id']); entry=at.isoformat(); due=deadline(at,config.holding_count,config.holding_unit).isoformat()
        else:
            cash+=money*(1-FEE); owned-=delta
            if owned< D('-.000000001'): raise ValueError('Fill exceeds owned Bitcoin')
            owned=max(D(0),owned)
            if owned==0: entry=None; due=None; entry_price=None
        db.execute('UPDATE btc_allocations SET cash=?,quantity=?,entry_at=?,exit_due_at=?,entry_price=? WHERE version_id=?',(str(cash),str(owned),entry,due,entry_price,row['version_id']))
        db.execute('UPDATE btc_orders SET status=?,broker_id=?,filled_qty=?,filled_notional=?,response_json=?,updated_at=? WHERE id=?',
                   (found['status'],found['id'],str(qty),str(notional),canonical(found),now.isoformat(),row['id']))


def sync_order(db,broker,row,now,allow_entries,lookup_only=False):
    allowed=allow_entries and bool(eligible(db,row['version_id'],now)) and (now-instant(row['created_at'])).total_seconds()<=90
    allocation=db.execute('SELECT risk_paused FROM btc_allocations WHERE version_id=?',(row['version_id'],)).fetchone()
    allowed=allowed and not allocation['risk_paused']
    found=broker.lookup(row['id'])
    if found is None:
        if lookup_only and row['side']=='buy': return
        if row['side']=='buy' and not allowed:
            if row['status']!='pending':
                raise ValueError('Submission remains uncertain; retain reservation and await broker lookup before canceling')
            with db: db.execute("UPDATE btc_orders SET status='canceled',updated_at=? WHERE id=?",(now.isoformat(),row['id']))
            return
        if row['side']=='buy':
            quote=broker.quote(now)
            if abs(D(str(quote['ap']))/D(row['reference_price'])-1)>D('.005'):
                if row['status']!='pending': raise ValueError('Uncertain entry moved beyond price limit; await lookup and cancellation')
                with db: db.execute("UPDATE btc_orders SET status='rejected' WHERE id=?",(row['id'],))
                return
        # A lost POST is retried only after lookup, always with the same ID.
        with db: db.execute("UPDATE btc_orders SET status='submitting' WHERE id=?",(row['id'],))
        found=broker.submit(row['id'],row['side'],row['quantity'])
    apply_fill(db,row,found,now)
    if not lookup_only and row['side']=='buy' and not allowed and found['status'] not in TERMINAL: broker.cancel(found['id'])



def sync_orders(db,broker,now,allow_entries,lookup_only=False):
    errors=[]
    for row in active_orders(db):
        try: sync_order(db,broker,row,now,allow_entries,lookup_only)
        except Exception as error:
            errors.append(error); health(db,"order:"+row["id"],now,str(error)[:500])
        else:
            with db: db.execute('DELETE FROM btc_health WHERE key=?',('order:'+row['id'],))
    if errors: raise errors[0]


def reconcile(db,broker,account,now):
    local=db.execute('SELECT * FROM btc_accounts WHERE id=?',(account['id'],)).fetchone()
    if not local: raise ValueError('Paper account identity changed')
    from .automation_fees import capture, reconcile_provisions
    capture(db,broker,local,now)
    unmatched=db.execute("SELECT 1 FROM btc_fees WHERE status='unattributed' LIMIT 1").fetchone()
    # Match gross fill totals minus actual activities. Ledger provisions remain
    # conservative for unposted fees; attributed fees are shown separately.
    orders=db.execute('SELECT * FROM btc_orders WHERE account_id=?',(account['id'],)).fetchall()
    gross_qty=sum((D(o['filled_qty'])*(1 if o['side']=='buy' else -1) for o in orders),D(0))
    gross_cash=D(local['initial_cash'])+sum((D(o['filled_notional'])*(1 if o['side']=='sell' else -1) for o in orders),D(0))
    actual_qty=D(0); actual_cash=D(0)
    for r in db.execute('SELECT payload_json FROM btc_fees WHERE account_id=?',(account['id'],)):
        f=json.loads(r[0]); actual_cash+=D(str(f.get('net_amount') or 0))
        if str(f.get('symbol','')).replace('/','') in ('BTC','BTCUSD'): actual_qty+=abs(D(str(f.get('qty') or 0)))
    positions=broker.positions()
    if any(str(p.get('symbol','')).replace('/','')!='BTCUSD' for p in positions): return False
    broker_qty=sum((D(p['qty']) for p in positions),D(0))
    expected_qty=gross_qty-actual_qty; expected_cash=gross_cash+actual_cash
    exact=abs(broker_qty-expected_qty)<=D('.00000001') and abs(D(account['cash'])-expected_cash)<=D('.02')
    # Fees may debit before their activity is published. Only a bounded, recent
    # fee provision can explain that temporary difference.
    pending_qty=sum((D(o['filled_qty'])*FEE for o in orders if o['side']=='buy' and (now-instant(o['updated_at'])).total_seconds()<48*3600),D(0))
    pending_cash=sum((D(o['filled_notional'])*FEE for o in orders if o['side']=='sell' and (now-instant(o['updated_at'])).total_seconds()<48*3600),D(0))
    if not expected_qty-pending_qty-D('.00000001')<=broker_qty<=expected_qty+D('.00000001'): return False
    if not expected_cash-pending_cash-D('.02')<=D(account['cash'])<=expected_cash+D('.02'): return False
    reconcile_provisions(db,now,exact)
    allocations=db.execute('SELECT * FROM btc_allocations').fetchall()
    adjusted=db.execute('SELECT * FROM btc_orders WHERE account_id=?',(account['id'],)).fetchall()
    modeled_qty=gross_qty-sum((D(o['filled_qty'])*FEE if o['side']=='buy' else D(0) for o in adjusted),D(0))-sum((D(o['fee_quantity_adjustment']) for o in adjusted),D(0))
    modeled_cash=gross_cash-sum((D(o['filled_notional'])*FEE if o['side']=='sell' else D(0) for o in adjusted),D(0))-sum((D(o['fee_cash_adjustment']) for o in adjusted),D(0))
    if abs(sum((D(a['quantity']) for a in allocations),D(0))-modeled_qty)>D('.000000001'): return False
    if abs(D(local['cash'])+sum((D(a['cash']) for a in allocations),D(0))-modeled_cash)>D('.01'): return False
    known={o['broker_id'] for o in orders if o['broker_id']}
    if any(o['id'] not in known for o in broker.open_orders()): return False
    if any(o['status']=='submitting' for o in orders): return False
    # Additional unallocated quantities/cash are never available to a sleeve.
    return not unmatched and all(D(a['cash'])>=0 and D(a['quantity'])>=0 for a in allocations)


def commands(db,broker,now):
    for row in db.execute("SELECT * FROM btc_control_commands WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchall():
        try:
            body=json.loads(row['payload_json']); action=row['action']
            if action=='fund': fund(db,broker,body['versions'],now)
            elif action=='reactivate':
                # Preserve the original high-water marks. Repeated risk breaches
                # cannot be bypassed by clicking resume.
                account=broker.account()
                if broker.positions() or broker.open_orders() or active_orders(db): raise ValueError('Risk reactivation requires all exits settled')
                local=db.execute('SELECT * FROM btc_accounts WHERE id=?',(account['id'],)).fetchone()
                if not local or D(account['cash'])<=D(local['high_water'])*D('.9'): raise ValueError('Account remains below its risk limit')
                if any(D(a['cash'])<=D(a['high_water'])*D('.9') for a in db.execute('SELECT * FROM btc_allocations')): raise ValueError('An allocation remains below its risk limit')
                with db:
                    db.execute('UPDATE btc_accounts SET risk_paused=0'); db.execute('UPDATE btc_allocations SET risk_paused=0')
                    audit(db,'bitcoin_risk_reactivated',account['id'],{})
            else: raise ValueError('Unknown coordinator command')
            with db: db.execute("UPDATE btc_control_commands SET status='succeeded' WHERE id=?",(row['id'],))
        except Exception as error:
            with db: db.execute("UPDATE btc_control_commands SET status='failed',error=? WHERE id=?",(str(error)[:500],row['id']))


def tick(db,history,broker,now):
    local=db.execute('SELECT * FROM btc_accounts').fetchone()
    if not local:
        commands(db,broker,now)
        local=db.execute('SELECT * FROM btc_accounts').fetchone()
        if not local: return
    try:
        account=broker.account()
        if account['id']!=local['id']: raise ValueError('Paper account identity changed')
    except Exception as error:
        health(db,'account',now,str(error)[:500]); return
    # Reconcile existing intents first. Qualification loss cancels buys; sells
    # retry even during quote outages, research failures, or operator pauses.
    try: sync_orders(db,broker,now,False,lookup_only=True)
    except Exception as error: health(db,'orders',now,str(error)[:500])
    else: health(db,'orders',now)
    quote=None; matching=False
    try:
        account=broker.account()
        if account['id']!=local['id']: raise ValueError('Paper account identity changed')
        matching=reconcile(db,broker,account,now)
    except Exception as error: health(db,'account',now,str(error)[:500])
    else: health(db,'account',now,None if matching else 'Account reconciliation or fee ownership unresolved; entries blocked')
    try: quote=broker.quote(now)
    except Exception as error: health(db,'quote',now,str(error)[:500])
    else: health(db,'quote',now)
    rows=db.execute('SELECT * FROM btc_allocations').fetchall()
    if quote:
        equity=D(local['cash'])+sum((D(a['cash'])+D(a['quantity'])*D(str(quote['bp']))*(1-FEE) for a in rows),D(0))
        high=max(D(local['high_water']),equity); risk=local['risk_paused'] or equity<=high*D('.9')
        with db: db.execute('UPDATE btc_accounts SET high_water=?,risk_paused=?,checked_at=?,equity=? WHERE id=?',(str(high),int(risk),now.isoformat(),str(equity),local['id']))
    else: risk=local['risk_paused']
    metadata=None
    for row in rows:
        version=row['version_id']; qty=D(row['quantity']); sleeve_risk=bool(row['risk_paused'])
        if quote:
            equity=D(row['cash'])+qty*D(str(quote['bp']))*(1-FEE)
            high=max(D(row['high_water']),equity); sleeve_risk |= equity<=high*D('.9')
            with db: db.execute('UPDATE btc_allocations SET high_water=?,risk_paused=? WHERE version_id=?',(str(high),int(sleeve_risk),version))
        due=bool(row['exit_due_at'] and now>=instant(row['exit_due_at']))
        config=config_for(db,version); action='hold'; reason=''
        try: metadata=metadata or broker.metadata()
        except Exception: metadata=None
        tradable=qty>0 and (not metadata or qty>=D(metadata['min_order_size']))
        if qty and not tradable and not active_orders(db,version):
            with db: db.execute('UPDATE btc_allocations SET entry_at=NULL,exit_due_at=NULL WHERE version_id=?',(version,))
            due=False
        system_risk=None
        if tradable and quote and config.protocol=='visual-rules-v1':
            from .rules import risk_exit
            system_risk=risk_exit(config,quote['bp'],row['entry_price'])
        if tradable and system_risk:action,reason='sell',system_risk
        if tradable and (risk or sleeve_risk or due): action='sell'; reason='Risk limit' if risk or sleeve_risk else 'Holding deadline'
        bars=None
        if quote:
            try: bars=latest_bars(history,config,now)
            except ValueError: pass
        if bars and action=='hold' and row['last_decision_at']!=bars[-1]['at']:
            action,reason=decision(config,bars,tradable)
        pending=active_orders(db,version)
        if pending:
            if action=='sell' or risk or sleeve_risk:
                for order in pending:
                    if order['side']=='buy' and order['broker_id']: broker.cancel(order['broker_id'])
            continue
        evaluation=eligible(db,version,now)
        if action=='buy' and (not matching or not evaluation or risk or sleeve_risk or not quote): action='hold'
        if action!='hold':
            try:
                metadata=metadata or broker.metadata()
                amount=qty if action=='sell' else min(D(row['cash'])/D('1.01'),equity*D(str(config.allocation)))/D(str(quote['ap']))
                amount=rounded_quantity(amount,metadata['min_trade_increment'])
                if D(amount)>=D(metadata['min_order_size']):
                    reserve(db,version,action,amount,quote['ap'] if quote else 1,now,evaluation,reason)
                    sync_orders(db,broker,now,matching and not risk)
                elif action=='sell': health(db,'dust:'+version,now,'Owned residual is below broker minimum; manual review required')
            except Exception as error: health(db,'execution:'+version,now,str(error)[:500])
        if bars and row['last_decision_at']!=bars[-1]['at']:
            with db: db.execute('UPDATE btc_allocations SET last_decision_at=?,state_json=? WHERE version_id=?',(bars[-1]['at'],canonical({'last_action':action,'last_reason':reason,'equity':str(equity)}),version))
    sync_orders(db,broker,now,matching and not risk)
    commands(db,broker,now)
