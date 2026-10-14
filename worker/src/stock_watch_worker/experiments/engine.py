"""Account-owner tick: reconcile, exits, valuation, then prospective decisions."""
from datetime import timedelta
import json
from . import evidence
from .model import NY, TERMINAL, boundary, canonical, digest, instant, stamp, money, signal, entry_session, trade_session, exit_reason
from .store import health, transaction
from .execution import active, active_symbol, available, position, session, reserve, sync, release_settlement

def expected_positions(db,asset):
    result={}
    for row in db.execute('''SELECT p.symbol,p.quantity FROM experiment_positions p JOIN experiment_instances i ON i.id=p.instance_id
            JOIN experiment_batches b ON b.id=i.batch_id WHERE b.asset=?''',(asset,)):
        result[row['symbol']]=result.get(row['symbol'],money(0))+money(row['quantity'])
    if asset=='stocks':
        from ..broker_reconciliation import _expected_positions
        # This adapter includes experiments; avoid recursively calling ourselves.
        return {k:money(v) for k,v in _expected_positions(db).items()}
    for row in db.execute('SELECT quantity FROM btc_allocations'):
        result['BTC/USD']=result.get('BTC/USD',money(0))+money(row[0])
    return result

def reconciled(db,broker,asset,account,allow_provisions=True):
    actual={str(r['symbol']).replace('BTCUSD','BTC/USD'):money(r['qty']) for r in broker.positions()}
    expected=expected_positions(db,asset)
    if asset=='bitcoin':
        from .legacy_totals import totals,experimental_delta
        legacy=totals(db,account['id']); quantity,_,_,_=experimental_delta(db,account['id'])
        expected={'BTC/USD':quantity+legacy['gross_qty']-legacy['actual_qty']}
    for symbol in set(actual)|set(expected):
        target=expected.get(symbol,money(0)); qty=actual.get(symbol,money(0))
        tolerance=max(money('.00000001'),abs(target)*money('.000001'))
        # Pending crypto fees can only reduce owned quantity, never increase it.
        provision=money(0)
        if asset=='bitcoin' and allow_provisions:
            provision=sum((money(r[0])*money('.0025') for r in db.execute("SELECT o.filled_qty FROM experiment_orders o WHERE o.account_id=? AND o.side='buy' AND NOT EXISTS(SELECT 1 FROM experiment_fees f WHERE f.order_id=o.id AND f.applied=1)",(account['id'],))),money(0))
        if not target-provision-tolerance<=qty<=target+tolerance:
            return False,'account_position_mismatch:'+symbol
    known={r[0] for r in db.execute('SELECT broker_id FROM experiment_orders WHERE account_id=? AND broker_id IS NOT NULL',(account['id'],))}
    if asset=='bitcoin': known.update(r[0] for r in db.execute('SELECT broker_id FROM btc_orders WHERE broker_id IS NOT NULL'))
    else:
        for table,column in (('paper_orders','broker_order_id'),('paper_exit_orders','broker_order_id'),('system_orders','broker_id')):
            known.update(r[0] for r in db.execute(f'SELECT {column} FROM {table} WHERE {column} IS NOT NULL'))
    if any(o['id'] not in known for o in broker.open_orders()): return False,'unattributed_open_order'
    if any(o['status'] in ('submitting','cancel_pending','uncertain') for o in active(db,account['id'])):
        return False,'order_reconciliation_pending'
    return True,None

from .fees import capture as capture_fees

def valuation(db,batch,quotes,now):
    total=money(150); positions=[]
    for row in db.execute('SELECT * FROM experiment_instances WHERE batch_id=?',(batch['id'],)):
        total+=money(row['cash'])
        for p in db.execute('SELECT * FROM experiment_positions WHERE instance_id=? AND CAST(quantity AS REAL)>0',(row['id'],)):
            if p['symbol'] not in quotes: raise ValueError('valuation_quote_unavailable:'+p['symbol'])
            value=money(p['quantity'])*money(quotes[p['symbol']]['bp']); total+=value
            positions.append({'instance':row['id'],'symbol':p['symbol'],'quantity':p['quantity'],'bid':quotes[p['symbol']]['bp']})
    day=now.astimezone(NY).date().isoformat()
    start=money(batch['day_equity']) if batch['day']==day and batch['day_equity'] else money(batch['equity'])
    peak=max(total,money(batch['high_water']))
    risk=batch['risk_reason']
    if total<=peak*money('.90'): risk='pool_drawdown_limit'
    elif total<=start*money('.98'): risk='daily_pool_loss_limit'
    with transaction(db):
        db.execute('UPDATE experiment_batches SET equity=?,high_water=?,day=?,day_equity=?,risk_reason=? WHERE id=?',
            (str(total),str(peak),day,str(start),risk,batch['id']))
        db.execute('INSERT OR IGNORE INTO experiment_valuations VALUES (?,?,?,?)',(batch['id'],stamp(now.replace(second=0,microsecond=0)),str(total),canonical(positions)))
        if risk and risk!=batch['risk_reason']:
            from ..systems.research import audit
            audit(db,'experiment_risk_paused',batch['id'],{'asset':batch['asset'],'reason':risk,'equity':str(total)})
    return risk

def write_decision(db,evidence_db,row,symbol,close,cutoff,now,outcome,reason,details,bars):
    identifier=digest({'instance':row['id'],'symbol':symbol,'bar':stamp(close)})
    evidence.pin(evidence_db,identifier,bars)
    with db:
        db.execute('INSERT OR IGNORE INTO experiment_decisions VALUES (?,?,?,?,?,?,?,?,?)',
            (identifier,row['id'],symbol,stamp(close),stamp(cutoff),stamp(now),outcome,reason,canonical({**details,'bars':[r['evidence_id'] for r in bars]})))
    return identifier

def state(db,identifier,name,reason,at=None):
    with db:
        db.execute('UPDATE experiment_instances SET state=?,reason=?,last_decision=COALESCE(?,last_decision) WHERE id=?',(name,reason,at,identifier))

def tick(db,evidence_db,broker,asset,now):
    batch=db.execute("SELECT * FROM experiment_batches WHERE asset=? AND status IN ('active','paused','exiting','expired')",(asset,)).fetchone()
    if not batch: return
    account=broker.account()
    if account['id']!=batch['account_id']: raise ValueError('Paper account identity changed')
    cal=session(db,now); valid=trade_session(asset,now,cal)
    for order in active(db,account['id']): sync(db,broker,order,now,can_submit=valid and order['side']=='sell')
    release_settlement(db,now)
    try: fees_ok=capture_fees(db,broker,batch,now)
    except Exception as error:
        fees_ok=False; health(db,'fees:'+asset,now,error)
    try: okay,block=reconciled(db,broker,asset,account)
    except Exception as error: okay,block=False,'account_reconciliation_unavailable'; health(db,'reconciliation:'+asset,now,error)
    if not fees_ok: okay,block=False,'fee_attribution_pending'
    from .accounting import cash_matches
    # Fetch after fill/fee reconciliation: the first account snapshot may precede
    # a fill acknowledged during this tick.
    account=broker.account()
    if not cash_matches(db,batch,account,now): okay,block=False,'account_cash_mismatch'
    if asset=='bitcoin' and fees_ok and okay:
        mature=db.execute("SELECT 1 FROM experiment_orders WHERE account_id=? AND updated<? AND CAST(filled_qty AS REAL)>0 LIMIT 1",(account['id'],stamp(now-timedelta(hours=48)))).fetchone()
        checked=db.execute("SELECT at FROM experiment_health WHERE component='fee-reserve-release:bitcoin'").fetchone()
        if mature and (not checked or now-instant(checked[0])>=timedelta(minutes=1)):
            from .fees import reconcile_provisions
            exact,_=reconciled(db,broker,asset,account,allow_provisions=False)
            if exact and cash_matches(db,batch,account,now,allow_provisions=False): reconcile_provisions(db,batch,now,settled=True)
            health(db,'fee-reserve-release:bitcoin',now)
    expired=now>=instant(batch['expires'])
    if expired and batch['status']!='expired':
        with db: db.execute("UPDATE experiment_batches SET status='expired' WHERE id=?",(batch['id'],))
    plan=json.loads(batch['plan_json']); configs={digest(c):c for c in plan['versions']}
    quotes={}; quote_errors={}
    for symbol in plan['versions'][0]['universe']:
        try: quotes[symbol]=evidence.quote(evidence_db,plan['versions'][0],symbol,now)
        except ValueError as error: quote_errors[symbol]=str(error)
    # Account reconciliation failures block new entries. Exits additionally need
    # confirmed broker holdings, preventing sale against missing ownership.
    try: risk=valuation(db,batch,quotes,now)
    except ValueError as error: risk=batch['risk_reason']; okay,block=False,str(error)
    instances=db.execute('SELECT * FROM experiment_instances WHERE batch_id=? ORDER BY id',(batch['id'],)).fetchall()
    for row in instances:
        cfg=configs[row['version_id']]
        for own in db.execute('SELECT * FROM experiment_positions WHERE instance_id=? AND CAST(quantity AS REAL)>0',(row['id'],)).fetchall():
            symbol=own['symbol']; q=quotes.get(symbol)
            reason=exit_reason(cfg,own,q['bp'] if q else None,now,expired,row['exit_requested'])
            previous=db.execute("SELECT * FROM experiment_orders WHERE instance_id=? AND symbol=? AND side='sell' ORDER BY created DESC,id DESC LIMIT 1",(row['id'],symbol)).fetchone()
            fallback=bool(previous and previous['status'] in ('canceled','expired','rejected') and now>=instant(previous['expires']) and money(previous['filled_qty'])<money(json.loads(previous['request_json'])['qty']) and not json.loads(previous['request_json']).get('type')=='market')
            if fallback: reason=previous['reason']
            if reason:
                state(db,row['id'],'exiting',reason)
                if not valid or active_symbol(db,account['id'],symbol): continue
                if previous and previous['status']=='rejected' and now<instant(previous['expires']): continue
                if block and block.startswith('account_position_mismatch'): continue
                try:
                    if not q and not fallback: q=broker.execution_quote(symbol)
                    identifier=reserve(db,row['id'],symbol,'sell',q,plan['preflight']['metadata'][symbol],now,reason,market=fallback,parent=previous['id'] if fallback else None)
                    sync(db,broker,db.execute('SELECT * FROM experiment_orders WHERE id=?',(identifier,)).fetchone(),now)
                except Exception as error: state(db,row['id'],'blocked',str(error))
    # A new account observation after all exit submissions avoids stale cash use.
    account=broker.account()
    for pending in active(db,account['id']):
        paused=db.execute('SELECT paused,exit_requested FROM experiment_instances WHERE id=?',(pending['instance_id'],)).fetchone()
        if pending['side']=='buy' and (risk or expired or paused['paused'] or paused['exit_requested']):
            sync(db,broker,pending,now,can_submit=False,force_cancel=True)
            continue
        if pending['side']=='buy' and pending['status']=='reserved':
            sync(db,broker,pending,now,can_submit=valid and okay and not risk and not expired)
    close=boundary(now-timedelta(seconds=35)); cutoff=close+timedelta(seconds=35)
    calendars=db.execute('SELECT * FROM experiment_calendar ORDER BY date').fetchall() if asset=='stocks' else None
    for row in instances:
        cfg=configs[row['version_id']]; symbols=cfg['universe']
        previous=instant(row['last_decision']) if row['last_decision'] else boundary(instant(batch['approved'])-timedelta(seconds=35))+timedelta(seconds=35)
        if cfg['family']!='control' and cutoff-previous>timedelta(minutes=5):
            with db: db.execute('INSERT OR IGNORE INTO experiment_decision_gaps VALUES (?,?,?,?,?)',
                (row['id'],stamp(previous+timedelta(minutes=5)),stamp(cutoff-timedelta(minutes=5)),stamp(now),
                 'No decisions recorded in this interval; includes market closures. Expired entries were not replayed.'))
        if cfg['family']=='control': symbols=['SPY'] if asset=='stocks' else ['BTC/USD']
        rotated=symbols[row['cursor']%len(symbols):]+symbols[:row['cursor']%len(symbols)]
        for symbol in rotated:
            decision_close=close
            decision_cutoff=cutoff
            if cfg['family']=='control':
                local=now.astimezone(NY); target=local.replace(hour=10,minute=5,second=0,microsecond=0)
                if local<target: continue
                decision_close=target.astimezone(now.tzinfo)
                decision_cutoff=decision_close
            if db.execute('SELECT 1 FROM experiment_decisions WHERE instance_id=? AND symbol=? AND bar_at=?',(row['id'],symbol,stamp(decision_close))).fetchone(): continue
            own=position(db,row['id'],symbol); held=bool(own and money(own['quantity'])>=money(plan['preflight']['metadata'][symbol]['minimum_quantity']))
            bars=[]; details={}; action='hold'; reason='waiting_signal'
            try:
                if asset=='stocks' and not valid: action,reason='hold','market_closed'
                elif cfg['family']=='control': action='hold' if held else 'buy'; reason='daily_control'
                else:
                    bars=evidence.history(evidence_db,cfg,symbol,close,cutoff,calendars)
                    news=evidence.fresh_news(evidence_db,symbol,cutoff)
                    action,reason,details=signal(cfg,bars,held,bool(news)); details['news']=news
                if action=='buy':
                    if expired: action,reason='hold','expired'
                    elif row['paused'] or row['exit_requested'] or risk: action,reason='hold',risk or 'paused'
                    elif not okay: action,reason='hold',block
                    elif symbol not in quotes: action,reason='hold',quote_errors[symbol]
                    elif not entry_session(asset,now,cal): action,reason='hold','outside_entry_session'
                    elif (cfg['family']=='control' and now>=decision_close+timedelta(minutes=5)) or (cfg['family']!='control' and now>cutoff+timedelta(seconds=25)):
                        action,reason='hold','missed_entry_window'
                    elif cfg['family']=='news_breakout':
                        nh=evidence_db.execute("SELECT * FROM health_events WHERE component='news' AND at<=? ORDER BY at DESC LIMIT 1",(stamp(now),)).fetchone()
                        if not nh or nh['error'] or (now-instant(nh['at'])).total_seconds()>120: action,reason='hold','news_feed_unavailable'
            except ValueError as error: action,reason='hold',str(error)
            identifier=write_decision(db,evidence_db,row,symbol,decision_close,decision_cutoff,now,action,reason,details,bars)
            if action in ('buy','sell'):
                try:
                    order=reserve(db,row['id'],symbol,action,quotes.get(symbol),plan['preflight']['metadata'][symbol],now,reason,decision=identifier,account_cash=account['cash'])
                    sync(db,broker,db.execute('SELECT * FROM experiment_orders WHERE id=?',(order,)).fetchone(),now)
                    with db: db.execute('UPDATE experiment_instances SET cursor=? WHERE id=?',((symbols.index(symbol)+1)%len(symbols),row['id']))
                except ValueError as error:
                    action,reason='hold',str(error)
                    with db: db.execute("UPDATE experiment_decisions SET outcome='blocked',reason=? WHERE id=?",(reason,identifier))
            status='expired' if expired else 'paused' if row['paused'] or risk else 'exiting' if row['exit_requested'] else 'ready' if action in ('buy','sell') else 'waiting_signal' if reason=='waiting_signal' else 'waiting_settlement' if 'settled' in reason else 'collecting' if reason.startswith('collecting') else 'blocked'
            state(db,row['id'],status,reason,stamp(decision_cutoff))
    for row in instances:
        held_rows=db.execute('SELECT * FROM experiment_positions WHERE instance_id=? AND CAST(quantity AS REAL)>0',(row['id'],)).fetchall()
        holdings=bool(held_rows)
        exit_due=any(exit_reason(configs[row['version_id']],p,quotes.get(p['symbol'],{}).get('bp'),now,expired,row['exit_requested']) for p in held_rows)
        orders=db.execute("SELECT side FROM experiment_orders WHERE instance_id=? AND status NOT IN ('filled','canceled','expired','rejected')",(row['id'],)).fetchall()
        if any(o['side']=='sell' for o in orders) or exit_due:
            state(db,row['id'],'exiting','exits_continue')
        elif risk or row['paused']: state(db,row['id'],'paused',risk or 'operator_pause')
        elif expired: state(db,row['id'],'expired','batch_expired')
        elif not okay: state(db,row['id'],'blocked',block)
        elif any(o['side']=='buy' for o in orders): state(db,row['id'],'ready','entry_order_pending')
        elif holdings: state(db,row['id'],'waiting_signal','holding; exits monitored')
        elif asset=='stocks' and not valid: state(db,row['id'],'waiting_signal','market_closed')
        if row['exit_requested'] and not holdings and not orders:
            with db: db.execute('UPDATE experiment_instances SET exit_requested=0 WHERE id=?',(row['id'],))
    if expired:
        owned=db.execute('''SELECT 1 FROM experiment_positions p JOIN experiment_instances i ON i.id=p.instance_id
            WHERE i.batch_id=? AND CAST(p.quantity AS REAL)>0''',(batch['id'],)).fetchone()
        unsettled=db.execute('''SELECT 1 FROM experiment_fills f JOIN experiment_orders o ON o.id=f.order_id JOIN experiment_instances i ON i.id=o.instance_id
            WHERE i.batch_id=? AND f.settled=0''',(batch['id'],)).fetchone()
        if not owned and not unsettled and not active(db,account['id']) and fees_ok:
            with db: db.execute("UPDATE experiment_batches SET status='completed' WHERE id=?",(batch['id'],))
    health(db,'execution:'+asset,now,None if okay else block,{'batch':batch['id'],'expired':expired})
