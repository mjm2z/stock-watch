"""Independent Bitcoin paper/shadow ticks with durable order identities."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import uuid

from .engine import SystemConfig, canonical, decision, instant
from .research import audit, now_iso
from .broker import rounded_quantity

TERMINAL = {'filled','canceled','expired','rejected','replaced'}


def observe(db, identifier, at, kind, payload):
    with db:
        db.execute('INSERT OR REPLACE INTO system_observations(deployment_id,observed_at,kind,payload_json) VALUES (?,?,?,?)',
                   (identifier, at, kind, canonical(payload)))


def start_shadow(db, version_id):
    version = db.execute('SELECT * FROM system_versions WHERE id=?',(version_id,)).fetchone()
    if not version:
        raise ValueError('Unknown system version')
    identifier = str(uuid.uuid4())
    with db:
        db.execute('INSERT INTO system_deployments(id,version_id,mode,started_at) VALUES (?,?,?,?)',
                   (identifier,version_id,'shadow',now_iso()))
        audit(db,'shadow_started',identifier,{})
    return identifier


def activation_checks(db, identifier, broker, now):
    row = db.execute('SELECT d.*,v.asset FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE d.id=?',(identifier,)).fetchone()
    if not row or row['asset'] != 'bitcoin':
        raise ValueError('Bitcoin paper activation requires a Bitcoin deployment')
    if row['mode'] != 'shadow':
        raise ValueError('Only a shadow deployment can be activated')
    observations = db.execute("SELECT observed_at FROM system_observations WHERE deployment_id=? AND kind='shadow' ORDER BY observed_at",(identifier,)).fetchall()
    days = {r[0][:10] for r in observations}
    if len(days) < 30 or (now-instant(observations[-1][0])).total_seconds() > 7200:
        raise ValueError('Requires observations on 30 distinct UTC days and a fresh shadow tick')
    result = db.execute("SELECT result_json FROM system_runs WHERE version_id=? AND status='succeeded' ORDER BY finished_at DESC LIMIT 1",(row['version_id'],)).fetchone()
    if not result:
        raise ValueError('A reviewed backtest is required')
    report = json.loads(result[0])
    if not report.get('folds'):
        raise ValueError('Insufficient walk-forward history; paper activation blocked')
    account = broker.account()
    if abs(float(account['cash'])-300) > .01 or broker.positions() or broker.open_orders():
        raise ValueError('Use an empty separate paper account with exactly $300 cash')
    broker.metadata()
    return row, account


def activate(db, identifier, broker, confirmation, now=None):
    if confirmation != identifier:
        raise ValueError('Confirmation must repeat the deployment ID')
    now = now or datetime.now(timezone.utc)
    row, account = activation_checks(db,identifier,broker,now)
    with db:
        db.execute("UPDATE system_deployments SET mode='paper',account_id=?,high_water=300,state_json=?,last_decision_at=NULL WHERE id=? AND mode='shadow'",
                   (account['id'],canonical({'paper_started_at':now.isoformat(),'cash_base':300}),identifier))
        audit(db,'paper_activated',identifier,{'account_id':account['id'],'confirmation':confirmation})


def reconcile_orders(db, deployment, broker, *, allow_entries=True, now=None):
    now=now or datetime.now(timezone.utc)
    rows = db.execute('SELECT * FROM system_orders WHERE deployment_id=?',(deployment,)).fetchall()
    for row in rows:
        if row['status'] in TERMINAL:
            continue
        found = broker.lookup(row['id'])
        expired=(now-instant(row['created_at'])).total_seconds()>900
        if found is None and row['side'] == 'buy' and (not allow_entries or expired):
            with db:
                db.execute("UPDATE system_orders SET status='canceled',updated_at=? WHERE id=?",(now_iso(),row['id']))
            continue
        if found is None:
            # An uncertain POST is looked up before resubmission with the identical ID.
            request = json.loads(row['request_json'])
            if row['side']=='buy':
                quote=broker.quote(now)
                reference=float(request.get('reference_price') or quote['ap'])
                if abs(float(quote['ap'])/reference-1)>.05:
                    with db: db.execute("UPDATE system_orders SET status='rejected',updated_at=? WHERE id=?",(now.isoformat(),row['id']))
                    continue
            found = broker.submit(row['id'],row['side'],request['qty'])
        with db:
            db.execute('UPDATE system_orders SET broker_id=?,status=?,filled_qty=?,filled_price=?,updated_at=?,response_json=? WHERE id=?',
                       (found['id'],found['status'],found.get('filled_qty','0'),found.get('filled_avg_price'),now_iso(),canonical(found),row['id']))


def order_intent(db, deployment, side, qty, at, broker, *, now=None):
    now=now or datetime.now(timezone.utc)
    reference=float(broker.quote(now)['ap']) if side=='buy' else None
    identifier = 'sys-'+uuid.uuid5(uuid.NAMESPACE_URL, f'{deployment}:{at}:{side}').hex
    with db:
        db.execute('INSERT OR IGNORE INTO system_orders(id,deployment_id,symbol,side,request_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                   (identifier,deployment,'BTC/USD',side,canonical({'qty':qty,'reference_price':reference}),now.isoformat(),now.isoformat()))
        audit(db,'order_intent',identifier,{'side':side,'qty':qty})
    reconcile_orders(db,deployment,broker,now=now)


def tick(db, broker, now=None):
    now = now or datetime.now(timezone.utc)
    at = now.isoformat()
    try:
        quote = broker.quote(now)
        with db:
            db.execute("INSERT OR REPLACE INTO bitcoin_observations(observed_at,kind,subject,payload_json) VALUES (?,'market','BTC/USD',?)",
                       (at,canonical({'provider':'Alpaca US','quote':quote})))
    except Exception as error:
        with db:
            db.execute("INSERT OR REPLACE INTO bitcoin_observations(observed_at,kind,subject,payload_json) VALUES (?,'error','market',?)",(at,canonical({'message':str(error)[:300]})))
    deployments = db.execute("SELECT d.*,v.config_json,v.config_sha256 FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE v.asset='bitcoin'").fetchall()
    for row in deployments:
        try:
            _tick_one(db,broker,row,now)
        except Exception as error:
            observe(db,row['id'],at,'error',{'message':str(error)[:500]})


def _tick_one(db,broker,row,now):
    at, identifier = now.isoformat(), row['id']
    config = SystemConfig(**json.loads(row['config_json']))
    if 'config_sha256' in row.keys() and config.sha256 != row['config_sha256']:
        raise ValueError('Immutable strategy hash mismatch')
    state = json.loads(row['state_json'])
    if row['mode'] == 'shadow':
        if row['last_decision_at'] == now.replace(minute=0,second=0,microsecond=0).isoformat():
            return
        bars = broker.bars(now)
        if row['last_decision_at'] == bars[-1]['at']:
            return
        with db:
            db.execute('INSERT OR IGNORE INTO bitcoin_market_bars VALUES (?,?,?)',(bars[-1]['at'],at,canonical(bars[-1])))
        quote = broker.quote(now)
        cash, qty = float(state.get('cash',300)), float(state.get('qty',0))
        equity = cash+qty*float(quote['bp'])
        peak = max(float(state.get('peak',300)),equity)
        paused = bool(state.get('paused')) or equity/peak-1 <= -.10
        action, reason = decision(config,bars,qty>0)
        if paused: action,reason = ('sell' if qty else 'hold'),'Shadow risk pause'
        price = float(quote['ap'] if action=='buy' else quote['bp'])
        fee = 0.
        if action=='buy' and not paused:
            budget=min(cash/1.0025,equity*config.allocation)
            qty=budget/(price*1.0005)*(1-.0025); fee=budget*.0025; cash-=budget
        elif action=='sell' and qty:
            proceeds=qty*price*.9995; fee=proceeds*.0025; cash+=proceeds-fee; qty=0.
        state.update({'cash':cash,'qty':qty,'peak':peak,'paused':paused,'fees':float(state.get('fees',0))+fee})
        observe(db,identifier,at,'shadow',{'bar_at':bars[-1]['at'],'action':action,'reason':reason,
                'price':price,'cash':cash,'qty':qty,'equity':cash+qty*float(quote['bp']),
                'drawdown':equity/peak-1,'fees':state['fees'],'execution':'subsequent observed quote plus 5 bps slippage and 25 bps fee'})
        with db:
            db.execute('UPDATE system_deployments SET last_decision_at=?,state_json=? WHERE id=?',(bars[-1]['at'],canonical(state),identifier))
        return
    if not row['account_id']:
        return
    account = broker.account()
    if account['id'] != row['account_id']:
        raise ValueError('Configured account does not match activated account')
    reconcile_orders(db,identifier,broker,allow_entries=row['mode'] != 'paused',now=now)
    positions = broker.positions()
    if any(p['symbol'].replace('/','') != 'BTCUSD' for p in positions):
        raise ValueError('Unexpected positions in Bitcoin account')
    actual = sum(Decimal(p['qty']) for p in positions)
    fees = broker.fees(state['paper_started_at'])
    orders = db.execute('SELECT * FROM system_orders WHERE deployment_id=?',(identifier,)).fetchall()
    expected = sum((Decimal(o['filled_qty']) * (1 if o['side']=='buy' else -1) for o in orders),Decimal(0))
    fee_quantity = sum((Decimal(f.get('qty','0')) for f in fees if str(f.get('symbol','')).replace('/','') in ('BTC','BTCUSD')),Decimal(0))
    expected += fee_quantity
    # Account for fee posting latency, conservatively. Unexplained differences block entries.
    matched = abs(expected-actual) <= Decimal('0.00000001')
    if row['mode']=='paused':
        known={o['id'] for o in orders}
        if any(o.get('client_order_id') not in known for o in broker.open_orders()):
            raise ValueError('Unmanaged orders detected; operator reconciliation required')
        active=[o for o in orders if o['status'] not in TERMINAL]
        for order in active:
            if order['side']=='buy' and order['broker_id']: broker.cancel(order['broker_id'])
        if active: return
        metadata=broker.metadata()
        qty=rounded_quantity(max(Decimal(0),min(actual,expected)),metadata['min_trade_increment'])
        if Decimal(qty)>=Decimal(metadata['min_order_size']):
            order_intent(db,identifier,'sell',qty,at,broker,now=now)
        elif actual>0:
            observe(db,identifier,at,'warning',{'message':'Residual balance below minimum executable order; operator review required'})
        observe(db,identifier,at,'decision',{'action':'sell' if actual else 'hold','reason':'Paused; manage owned exposure without requiring a fresh entry quote'})
        return
    quote = broker.quote(now)
    broker_equity = float(account['cash']) + float(actual)*float(quote['bp'])
    gross_traded = sum(float(o['filled_qty'])*float(o['filled_price'] or 0) for o in orders)
    actual_fee_usd = sum(abs(float(f.get('net_amount') or 0)) + abs(float(f.get('qty') or 0))*float(f.get('price') or quote['bp']) for f in fees)
    modeled_cost_adjustment = max(0.,gross_traded*.0025-actual_fee_usd)+gross_traded*.0005
    equity = broker_equity-modeled_cost_adjustment
    expected_cash = 300 + sum(float(o['filled_qty'])*float(o['filled_price'] or 0)*(1 if o['side']=='sell' else -1) for o in orders) + sum(float(f.get('net_amount') or 0) for f in fees)
    cash_matched = abs(expected_cash-float(account['cash'])) <= .02
    matched = matched and cash_matched
    high = max(row['high_water'],equity)
    risk = equity/high-1 <= -.10
    paused = row['mode']=='paused' or risk
    with db:
        db.execute('UPDATE system_deployments SET high_water=?,mode=? WHERE id=?',(high,'paused' if paused else 'paper',identifier))
        if risk and row['mode'] != 'paused':
            audit(db,'drawdown_pause',identifier,{'equity':equity,'high_water':high})
    observe(db,identifier,at,'portfolio',{'equity':equity,'cash':float(account['cash']),'qty':str(actual),
            'broker_equity':broker_equity,'modeled_cost_adjustment':modeled_cost_adjustment,
            'drawdown':equity/high-1,'reconciled':matched,'broker_fees':fees,'paused':paused})
    active = [o for o in orders if o['status'] not in TERMINAL]
    foreign = [o for o in broker.open_orders() if o.get('client_order_id') not in {o['id'] for o in orders}]
    if foreign:
        raise ValueError('Unmanaged orders detected; operator reconciliation required')
    if paused:
        for order in active:
            if order['side']=='buy' and order['broker_id']:
                broker.cancel(order['broker_id'])
        if active:
            return  # Wait for cancellation/fill acknowledgement before sizing an exit.
        action, reason = 'sell', 'Portfolio paused: exit remaining owned exposure'
    else:
        if not matched:
            raise ValueError('Position/cash/fee reconciliation mismatch; entries blocked')
        if active:
            return
        bars = broker.bars(now)
        if row['last_decision_at'] == bars[-1]['at']:
            return
        action, reason = decision(config,bars,actual>0)
        if action=='buy' and (now-instant(bars[-1]['at'])).total_seconds()>900:
            action,reason='hold','Entry signal expired after 15 minutes'
        state['bar_at'] = bars[-1]['at']
    metadata = broker.metadata()
    if action == 'buy':
        # Cash must cover fees; a paper account reset/deposit cannot increase the allocation.
        budget = min(300*config.allocation, equity*config.allocation, float(account['cash'])/1.005)
        qty = rounded_quantity(budget/float(quote['ap']),metadata['min_trade_increment'])
    else:
        qty = rounded_quantity(max(Decimal(0),min(actual,expected)),metadata['min_trade_increment'])
    if action in ('buy','sell') and Decimal(qty) >= Decimal(metadata['min_order_size']):
        order_intent(db,identifier,action,qty,at if paused else state['bar_at'],broker,now=now)
    elif action == 'sell' and actual > 0:
        observe(db,identifier,at,'warning',{'message':'Residual balance below minimum executable order; operator review required'})
    observe(db,identifier,at,'decision',{'action':action,'reason':reason})
    if not paused:
        with db:
            db.execute('UPDATE system_deployments SET last_decision_at=?,state_json=? WHERE id=?',(state['bar_at'],canonical(state),identifier))
