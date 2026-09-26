"""Deterministic 100-scenario suites, resumable caching, and entry qualification."""
from datetime import datetime, timedelta, timezone
from statistics import median
import json
import math
import uuid
from .automation_config import BitcoinConfig
from .automation_replay import PROFILES, source_key, replay
from .engine import canonical, instant
from .timeframes import advance, boundary, deadline, evidence_expiry, next_review


def config_for(db, version):
    row=db.execute('SELECT config_json FROM system_versions WHERE id=?',(version,)).fetchone()
    if not row: raise ValueError('Unknown version')
    return BitcoinConfig(**json.loads(row[0]))


def windows(config, cutoff, observed_start=None):
    end=boundary(cutoff,config.timeframe)
    # Calendar holding durations use their worst-case month length.
    holding=(timedelta(days=31*config.holding_count) if config.holding_unit=='months'
             else deadline(end,config.holding_count,config.holding_unit)-end)
    bar_seconds=(advance(end,config.timeframe)-end).total_seconds()
    if config.timeframe=='1Month': bar_seconds=28*86400
    count=max(12,math.ceil(2*holding.total_seconds()/bar_seconds))
    if observed_start:
        first=boundary(observed_start,config.timeframe)
        available=((end.year-first.year)*12+end.month-first.month if config.timeframe=='1Month'
                   else int((end-first).total_seconds()/bar_seconds))
        available=max(0,available-max(config.slow,config.entry)-2)
        # Expand with observed history, never with profitability. Otherwise a
        # slow system could be permanently stuck below the unique-trade floor.
        count=max(count,(available//23)*4)
    stride=math.ceil(count/4)
    return [(advance(end,config.timeframe,-count-stride*(19-i)),advance(end,config.timeframe,-stride*(19-i))) for i in range(20)]


def queue(db, version, now, due=None):
    config=config_for(db,version); due=due or now
    if db.execute("SELECT 1 FROM btc_evaluations WHERE version_id=? AND status IN ('queued','running')",(version,)).fetchone(): return None
    identifier=str(uuid.uuid4()); cutoff=now.isoformat()
    allocation=db.execute('SELECT budget FROM btc_allocations WHERE version_id=?',(version,)).fetchone()
    budget=allocation[0] if allocation else '60'
    first=db.execute('SELECT MIN(at) FROM btc_forward WHERE version_id=?',(version,)).fetchone()[0]
    with db:
        result=db.execute('INSERT OR IGNORE INTO btc_evaluations(id,version_id,cutoff,due_at,expires_at,created_at,budget) VALUES (?,?,?,?,?,?,?)',
                         (identifier,version,cutoff,due.isoformat(),evidence_expiry(now,config.timeframe).isoformat(),cutoff,budget))
        if not result.rowcount: return None
        for index,(start,end) in enumerate(windows(config,now,instant(first) if first else None)):
            for profile in PROFILES:
                db.execute('INSERT INTO btc_scenarios(id,evaluation_id,window_index,profile,starts_at,ends_at) VALUES (?,?,?,?,?,?)',
                           (str(uuid.uuid4()),identifier,index,profile,start.isoformat(),end.isoformat()))
        db.execute('''INSERT INTO btc_qualifications(version_id,status,reason,checked_at,next_review_at)
          VALUES (?,'collecting','Collecting research and forward evidence',?,?) ON CONFLICT(version_id) DO NOTHING''',
          (version,cutoff,next_review(now,config.timeframe).isoformat()))
    return identifier


def schedule(db,now):
    for row in db.execute('SELECT e.version_id,q.next_review_at FROM btc_enrollments e LEFT JOIN btc_qualifications q ON q.version_id=e.version_id WHERE e.active=1').fetchall():
        due=instant(row['next_review_at']) if row['next_review_at'] else now
        if due<=now:
            queue(db,row['version_id'],now,due)
    with db:
        db.execute("UPDATE btc_qualifications SET status='suspended',reason='Evaluation expired; entries blocked',failed_once=1,pass_streak=0 WHERE status='qualified' AND evaluation_id IN (SELECT id FROM btc_evaluations WHERE expires_at<=?)",(now.isoformat(),))
    for row in db.execute("SELECT version_id FROM btc_qualifications WHERE status='qualified'").fetchall():
        ready,reason=forward_ready(db,row[0],now)
        if not ready:
            with db: db.execute("UPDATE btc_qualifications SET status='suspended',reason=?,failed_once=1,pass_streak=0 WHERE version_id=?",(reason,row[0]))


def summarize(results,trade_stats=None):
    base=[r for r in results if r['profile']=='base']
    unique={t['id']:t for r in base for t in r['trades']}
    independent=0; last_end=None
    for r in sorted(base,key=lambda r:r['starts_at']):
        if last_end is None or r['starts_at']>=last_end:
            independent+=1; last_end=r['ends_at']
    positive=sum(r['net_return']>0 for r in base)/len(base) if base else 0
    profiles={p:{'mean_net_return':sum(r['net_return'] for r in results if r['profile']==p)/20,
                 'maximum_drawdown':max((r['drawdown'] for r in results if r['profile']==p),default=1)} for p in PROFILES}
    n,wins=trade_stats if trade_stats is not None else (len(unique),sum(t['pnl']>0 for t in unique.values()))
    rate=wins/n if n else None
    # Wilson interval describes observed trades, not future trade probability.
    interval=None
    if n:
        center=(rate+1.96**2/(2*n))/(1+1.96**2/n)
        half=1.96*math.sqrt(rate*(1-rate)/n+1.96**2/(4*n*n))/(1+1.96**2/n)
        interval=[max(0,center-half),min(1,center+half)]
    reasons=[]
    if len(results)!=100 or any(not r['valid'] for r in results): reasons.append('All 100 scenarios need complete observed data and executable quote coverage')
    if n<30: reasons.append(f'Only {n}/30 unique completed trades')
    if independent<5: reasons.append(f'Only {independent}/5 independent windows')
    if positive<.6: reasons.append('Fewer than 60% profitable base windows')
    med=median([r['net_return'] for r in base]) if base else 0
    if med<=0: reasons.append('Median base return is not positive')
    if any(v['mean_net_return']<=0 for v in profiles.values()): reasons.append('A cost profile has nonpositive mean net return')
    if any(v['maximum_drawdown']>.1 for v in profiles.values()): reasons.append('A profile exceeds 10% drawdown')
    return {'passed':not reasons,'reasons':reasons,'unique_trades':n,'independent_windows':independent,
            'overlapping_windows':20-independent,'profitable_windows':positive,'median_base_return':med,
            'profiles':profiles,'trade_win_rate':rate,'trade_win_interval':interval,
            'scenario_pass_rate':sum(r['valid'] and r['net_return']>0 and r['drawdown']<=.1 for r in results)/100,
            'mean_exposure':sum(r['exposure'] for r in base)/20,'mean_turnover':sum(r['turnover'] for r in base)/20,
            'mean_costs':sum(r['costs'] for r in base)/20,
            'limitations':['Overlapping windows are not independent trials. Win rates are historical, not predicted probabilities.',
                           'Returns include conservatively marked open positions; only completed trades count toward the minimum.']}


def forward_ready(db,version,now):
    cached=db.execute('SELECT * FROM btc_health WHERE key=?',('evidence:'+version,)).fetchone()
    if not cached or (now-instant(cached['at'])).total_seconds()>=3600:
        row=db.execute('SELECT MIN(at) AS first,MAX(at) AS last,COUNT(DISTINCT substr(at,1,10)) AS days FROM btc_forward WHERE version_id=?',(version,)).fetchone()
        error=None
        if not row['first'] or (now-instant(row['first'])).total_seconds()<30*86400 or row['days']<30:
            error='At least 30 calendar days of observed forward performance are required'
        if not error:
            cutoff=(now-timedelta(days=30,hours=2)).isoformat()
            gap=db.execute('''SELECT MAX((julianday(at)-julianday(previous))*86400) FROM
              (SELECT at,LAG(at) OVER (ORDER BY at) AS previous FROM btc_forward WHERE version_id=? AND at>=?)''',(version,cutoff)).fetchone()[0]
            if gap is None or gap>7201: error='Forward observation history has an unresolved gap exceeding two hours'
        # Commit only when the caller is not holding a reservation transaction.
        nested=db.in_transaction
        db.execute('INSERT INTO btc_health VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET at=excluded.at,error=excluded.error',('evidence:'+version,now.isoformat(),error))
        if not nested: db.commit()
        cached={'error':error}
    if cached['error']: return False,cached['error']
    latest=db.execute('SELECT at FROM btc_forward WHERE version_id=? ORDER BY at DESC LIMIT 1',(version,)).fetchone()
    if not latest or (now-instant(latest[0])).total_seconds()>3600: return False,'Forward observations are stale'
    health=db.execute("SELECT * FROM btc_health WHERE key='data'").fetchone()
    if not health or health['error'] or (now-instant(health['at'])).total_seconds()>120:
        return False,'Market data health is unresolved'
    forward=db.execute('SELECT * FROM btc_health WHERE key=?',('forward:'+version,)).fetchone()
    if not forward or forward['error'] or (now-instant(forward['at'])).total_seconds()>120:
        return False,'Forward data health is unresolved'
    return True,''


def finish(db,evaluation,now,trade_db=None):
    rows=db.execute('SELECT * FROM btc_scenarios WHERE evaluation_id=? ORDER BY window_index,profile',(evaluation['id'],)).fetchall()
    results=[{**json.loads(r['result_json']),'profile':r['profile'],'starts_at':r['starts_at'],'ends_at':r['ends_at']} for r in rows]
    from .trade_store import unique_stats
    stats=unique_stats(trade_db,[r['cache_key'] for r in rows if r['profile']=='base']) if trade_db else None
    summary=summarize(results,stats); ready,reason=forward_ready(db,evaluation['version_id'],now)
    if not ready: summary['reasons'].append(reason); summary['passed']=False
    summary['cached']=sum(r['reused'] for r in rows); summary['new']=100-summary['cached']
    previous=db.execute('SELECT * FROM btc_qualifications WHERE version_id=?',(evaluation['version_id'],)).fetchone()
    streak=(previous['pass_streak']+1) if summary['passed'] else 0
    failed=previous['failed_once'] or (not summary['passed'] and (previous['status'] in ('qualified','suspended') or (ready and all(r['valid'] for r in results))))
    if instant(evaluation['expires_at'])<=now:
        summary['passed']=False; summary['reasons'].append('Evidence expired before evaluation finished')
        failed=True; streak=0
    qualified=summary['passed'] and (not failed or streak>=2) and instant(evaluation['expires_at'])>now
    status='qualified' if qualified else ('suspended' if failed else 'collecting')
    reasons='; '.join(summary['reasons']) or ('Passed; waiting for second scheduled evaluation' if not qualified else 'All qualification gates passed')
    with db:
        changed=db.execute("UPDATE btc_evaluations SET status='succeeded',progress=100,result_json=?,finished_at=? WHERE id=? AND status IN ('queued','running')",(canonical(summary),now.isoformat(),evaluation['id']))
        if not changed.rowcount: return
        db.execute('''UPDATE btc_qualifications SET evaluation_id=?,status=?,reason=?,pass_streak=?,failed_once=?,checked_at=?,next_review_at=? WHERE version_id=?''',
          (evaluation['id'],status,reasons,streak,int(failed),now.isoformat(),next_review(now,config_for(db,evaluation['version_id']).timeframe).isoformat(),evaluation['version_id']))


def run_one(db,history,now=None):
    from .trade_store import connect_trades
    now=now or datetime.now(timezone.utc); schedule(db,now)
    evaluation=db.execute("SELECT * FROM btc_evaluations WHERE status IN ('queued','running') ORDER BY due_at LIMIT 1").fetchone()
    if not evaluation: return False
    row=db.execute("SELECT * FROM btc_scenarios WHERE evaluation_id=? AND status!='succeeded' ORDER BY window_index,profile LIMIT 1",(evaluation['id'],)).fetchone()
    if not row:
        trade_db=connect_trades(history)
        try: finish(db,evaluation,now,trade_db)
        finally: trade_db.close()
        return True
    config=config_for(db,evaluation['version_id'])
    with db: db.execute("UPDATE btc_evaluations SET status='running' WHERE id=?",(evaluation['id'],))
    trade_db=connect_trades(history)
    try:
        # Fixed cutoff makes retries deterministic; cache verifies every source row.
        meta=history.execute('SELECT payload_json FROM metadata WHERE at<=? ORDER BY at DESC LIMIT 1',(evaluation['cutoff'],)).fetchone()
        metadata=json.loads(meta[0]) if meta else None
        capital=float(evaluation['budget'])
        key=source_key(history,config,row['starts_at'],row['ends_at'],evaluation['cutoff'],row['profile'],capital,metadata)
        cached=db.execute('SELECT result_json FROM btc_scenario_cache WHERE key=?',(key,)).fetchone()
        if cached and trade_db.execute('SELECT COUNT(*) FROM trades WHERE cache_key=?',(key,)).fetchone()[0]!=json.loads(cached[0]).get('trade_count',0): cached=None
        if cached: result=cached[0]
        else:
            with trade_db: trade_db.execute('DELETE FROM trades WHERE cache_key=?',(key,))
            def sink(trade):
                trade_db.execute('INSERT INTO trades VALUES (?,?,?,?,?)',(key,trade['id'],trade['exit'],trade['pnl'],trade['cost_basis']))
            with trade_db:
                result=canonical(replay(history,config,row['starts_at'],row['ends_at'],evaluation['cutoff'],row['profile'],sink,capital,metadata))
        with db:
            db.execute('INSERT OR IGNORE INTO btc_scenario_cache VALUES (?,?,?)',(key,result,now.isoformat()))
            db.execute("UPDATE btc_scenarios SET status='succeeded',cache_key=?,reused=?,result_json=?,error=NULL WHERE id=?",(key,int(bool(cached)),result,row['id']))
            db.execute("UPDATE btc_evaluations SET progress=(SELECT COUNT(*) FROM btc_scenarios WHERE evaluation_id=? AND status='succeeded'),error=NULL WHERE id=?",(evaluation['id'],evaluation['id']))
        if db.execute("SELECT COUNT(*) FROM btc_scenarios WHERE evaluation_id=? AND status='succeeded'",(evaluation['id'],)).fetchone()[0]==100: finish(db,evaluation,now,trade_db)
    except Exception as error:
        with db:
            db.execute("UPDATE btc_evaluations SET status='failed',error=?,finished_at=? WHERE id=?",(str(error)[:500],now.isoformat(),evaluation['id']))
            db.execute("UPDATE btc_qualifications SET status='suspended',reason='Research failed; exits remain active',failed_once=1,pass_streak=0,next_review_at=? WHERE version_id=?",(next_review(now,config.timeframe).isoformat(),evaluation['version_id']))
        raise
    finally: trade_db.close()
    return True
