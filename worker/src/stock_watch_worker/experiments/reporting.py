"""One ledger projection for automated and manual daily paper activity."""
from datetime import datetime, timedelta
from .model import NY, instant, stamp, money

def projection(db,manual_db,start,end):
    """Count distinct orders with actual incremental fills in a bounded window."""
    a,b=stamp(start),stamp(end); result={}
    groups=(('scanner','stocks'),('systems','stocks'),('systems','bitcoin'),('experiments','stocks'),('experiments','bitcoin'),('control','stocks'),('control','bitcoin'),('manual','stocks'),('manual','bitcoin'))
    for group,asset in groups: result[(group,asset)]={'group':group,'asset':asset,'buys':0,'sells':0,'filled_orders':0,'notional':money(0),'open_positions':0}
    seen=set()
    def consume(rows):
        for row in rows:
            key=(row['scope'],row['asset']); order=(row['scope'],row['asset'],row['order_id'])
            if key not in result: continue
            if order not in seen:
                result[key]['buys' if row['side']=='buy' else 'sells']+=1
                result[key]['filled_orders']+=1; seen.add(order)
            result[key]['notional']+=money(row['notional'])
    # datetime() accepts legacy ISO variants without lexicographic timezone bugs.
    consume(db.execute("""SELECT 'scanner' scope,'stocks' asset,o.id order_id,'buy' side,f.notional_usd notional FROM paper_fills f JOIN paper_orders o ON o.id=f.order_id
        WHERE julianday(f.filled_at)>=julianday(?) AND julianday(f.filled_at)<julianday(?) UNION ALL
        SELECT 'scanner','stocks',o.id,'sell',f.notional_usd FROM paper_exit_fills f JOIN paper_exit_orders o ON o.id=f.exit_order_id
        WHERE julianday(f.filled_at)>=julianday(?) AND julianday(f.filled_at)<julianday(?)""",(a,b,a,b)))
    result[('scanner','stocks')]['open_positions']=db.execute("SELECT count(DISTINCT instrument_id) FROM paper_trade_lots WHERE status IN ('open','closing')").fetchone()[0]
    consume(db.execute("""SELECT 'systems' scope,'bitcoin' asset,o.id order_id,o.side,f.notional FROM btc_fills f JOIN btc_orders o ON o.id=f.order_id
        WHERE julianday(f.at)>=julianday(?) AND julianday(f.at)<julianday(?)""",(a,b)))
    result[('systems','bitcoin')]['open_positions']=db.execute('SELECT count(*) FROM btc_allocations WHERE CAST(quantity AS REAL)>0').fetchone()[0]
    consume(db.execute("""SELECT 'systems' scope,v.asset,o.id order_id,o.side,f.notional FROM execution_fill_events f JOIN system_orders o ON o.id=f.order_id
        JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id
        WHERE julianday(f.at)>=julianday(?) AND julianday(f.at)<julianday(?)""",(a,b)))
    from ..systems.stocks import system_positions
    result[('systems','stocks')]['open_positions']=len(system_positions(db))
    consume(db.execute("""SELECT CASE v.family WHEN 'control' THEN 'control' ELSE 'experiments' END scope,b.asset,o.id order_id,o.side,f.notional
        FROM experiment_fills f JOIN experiment_orders o ON o.id=f.order_id JOIN experiment_instances i ON i.id=o.instance_id
        JOIN experiment_batches b ON b.id=i.batch_id JOIN experiment_versions v ON v.id=i.version_id
        WHERE f.at>=? AND f.at<?""",(a,b)))
    for row in db.execute("""SELECT CASE v.family WHEN 'control' THEN 'control' ELSE 'experiments' END scope,b.asset,count(*) n FROM experiment_positions p
        JOIN experiment_instances i ON i.id=p.instance_id JOIN experiment_batches b ON b.id=i.batch_id JOIN experiment_versions v ON v.id=i.version_id
        WHERE CAST(p.quantity AS REAL)>0 GROUP BY scope,b.asset"""):
        result[(row['scope'],row['asset'])]['open_positions']=row['n']
    # Manual fills are cumulative snapshots. LAG converts them to actual deltas.
    if manual_db:
        rows=manual_db.execute("""WITH deltas AS (SELECT f.*,CAST(cumulative_notional AS REAL)-COALESCE(LAG(CAST(cumulative_notional AS REAL)) OVER(PARTITION BY instruction_id ORDER BY observed,CAST(cumulative_qty AS REAL)),0) delta FROM fills f)
            SELECT 'manual' scope,i.asset,i.id order_id,i.side,d.delta notional FROM deltas d JOIN instructions i ON i.id=d.instruction_id
            WHERE d.observed>=? AND d.observed<? AND d.delta>0""",(start.timestamp(),end.timestamp()))
        consume(rows)
        for row in manual_db.execute("SELECT asset,symbol,SUM(CASE side WHEN 'buy' THEN CAST(filled_qty AS REAL) ELSE -CAST(filled_qty AS REAL) END) q FROM instructions GROUP BY asset,symbol HAVING q>0"):
            result[('manual',row['asset'])]['open_positions']+=1
    states=[dict(r) for r in db.execute("""SELECT b.asset,i.state,i.reason,count(*) n FROM experiment_instances i JOIN experiment_batches b ON b.id=i.batch_id
        WHERE b.status IN ('active','paused','expired','exiting') GROUP BY b.asset,i.state,i.reason""")]
    return {'start':a,'end':b,'groups':[{**r,'notional':str(r['notional'])} for r in result.values()],'experiment_states':states}

def message(report):
    local=instant(report['end']).astimezone(NY)
    lines=['StockWatch · Paper · '+local.strftime('%b %-d'), 'Filled orders since the previous daily cutoff:']
    for asset,label in (('stocks','Stocks'),('bitcoin','Bitcoin')):
        rows=[r for r in report['groups'] if r['asset']==asset and r['group']!='manual']
        buys=sum(r['buys'] for r in rows); sells=sum(r['sells'] for r in rows); positions=sum(r['open_positions'] for r in rows)
        lines.append(f'{label}: {buys} buys · {sells} sells · {positions} open positions')
        scanner=next((r for r in rows if r['group']=='scanner'),None)
        if scanner and scanner['filled_orders']: lines.append(f"  Scanner: {scanner['buys']} buys · {scanner['sells']} sells")
        control=next(r for r in rows if r['group']=='control')
        if control['filled_orders']: lines.append(f"  Control: {control['buys']} buys · {control['sells']} sells")
        states=[r for r in report['experiment_states'] if r['asset']==asset]
        if not states: lines.append('  Experiments: no approved active batch')
        elif not buys:
            reasons=list(dict.fromkeys((r['reason'] or r['state']).replace('_',' ') for r in states))
            lines.append('  Experiments: '+'; '.join(reasons[:2]))
    manual=[r for r in report['groups'] if r['group']=='manual']
    lines.append(f"Manual: {sum(r['buys'] for r in manual)} buys · {sum(r['sells'] for r in manual)} sells")
    lines.append('http://stockwatch.home.arpa/systems?tab=experiments')
    return '\n'.join(lines)

def due_cutoff(now,scheduled):
    hour,minute=map(int,scheduled.split(':'))
    if not 0<=hour<=23 or not 0<=minute<=59: raise ValueError('Invalid digest time')
    local=datetime.fromtimestamp(now,NY)
    cutoff=local.replace(hour=hour,minute=minute,second=0,microsecond=0)
    if local<cutoff: cutoff-=timedelta(days=1)
    return cutoff

def daily_digest(manual):
    import os
    from contextlib import closing
    from ..manual.systems import database
    from ..manual.store import notify
    now=manual.now(); cutoff=due_cutoff(now,os.environ.get('STOCK_WATCH_DIGEST_TIME','20:00'))
    key='digest:'+cutoff.date().isoformat()
    if manual.db.execute('SELECT 1 FROM outbox WHERE id=?',(key,)).fetchone(): return
    # Catch up one latest cutoff, never replay a backlog of daily messages.
    try:
        with closing(database()) as main:
            report=projection(main,manual.db,cutoff-timedelta(days=1),cutoff)
        text=message(report)
    except Exception:
        import json
        from ..manual.messages import digest as manual_digest
        text=manual_digest([json.loads(r['payload']) for r in manual.db.execute('SELECT * FROM snapshots')],
            [dict(r) for r in manual.db.execute('SELECT status FROM instructions')],
            [dict(r) for r in manual.db.execute('SELECT * FROM health')],now)
        text+='\nManual account above. Automated activity unavailable; check collection health.'
    with manual.db:
        notify(manual.db,key,text,now)
        manual.db.execute("INSERT OR REPLACE INTO integration_state VALUES ('paper_digest_cutoff',?)",(stamp(cutoff),))
