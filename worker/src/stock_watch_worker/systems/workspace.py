"""Durable UI jobs. No request handler performs network research or broker writes."""
from datetime import datetime,timezone
import json
import math
import os
from pathlib import Path
from urllib.parse import urlencode
from .engine import canonical,instant
from .research import now_iso,register_version,audit
from ..http import UrllibTransport,require_success


def chart(payload,transport=None):
    prefix='BITCOIN_ALPACA' if os.environ.get('BITCOIN_ALPACA_API_KEY_ID') and os.environ.get('BITCOIN_ALPACA_API_SECRET_KEY') else 'ALPACA'
    headers={'APCA-API-KEY-ID':os.environ.get(prefix+'_API_KEY_ID',''),'APCA-API-SECRET-KEY':os.environ.get(prefix+'_API_SECRET_KEY','')}
    if not all(headers.values()):raise ValueError('Market-data credentials are not configured; no funded account is required')
    params={'symbols':'BTC/USD','timeframe':payload['frame'],'start':payload['start'],'end':payload['end'],'limit':10000,'sort':'asc'}
    transport=transport or UrllibTransport()
    by_time={};seen_tokens=set();partial=False
    for _ in range(40):
        response=transport.request('GET','https://data.alpaca.markets/v1beta3/crypto/us/bars?'+urlencode(params),headers=headers,timeout=30)
        result=require_success('crypto-chart',response)
        for row in result.get('bars',{}).get('BTC/USD',[]):
            if not all(isinstance(row.get(k),(int,float)) and math.isfinite(row[k]) for k in ('o','h','l','c','v')):raise ValueError('Provider returned invalid prices')
            if not 0<row['l']<=min(row['o'],row['c'])<=max(row['o'],row['c'])<=row['h'] or row['v']<0:raise ValueError('Provider returned invalid price range')
            instant(row['t'])
            by_time[row['t']]={'at':row['t'],'open':row['o'],'high':row['h'],'low':row['l'],'close':row['c'],'volume':row['v']}
            if len(by_time)>6000:raise ValueError('Chart exceeds display limit; choose a shorter range')
        token=result.get('next_page_token')
        partial=bool(token)
        if not token:break
        if not isinstance(token,str) or token in seen_tokens:raise ValueError('Provider repeated or invalid pagination token')
        seen_tokens.add(token);params['page_token']=token
    bars=sorted(by_time.values(),key=lambda row:instant(row['at']))
    from .timeframes import advance
    gaps=sum(instant(b['at'])>advance(instant(a['at']),payload['frame']) for a,b in zip(bars,bars[1:]))
    return {'gaps':gaps,'bars':bars,'provider':'Alpaca US','resolution':payload['frame'],'requestedStart':payload['start'],'requestedEnd':payload['end'],
            'coverageStart':bars[0]['at'] if bars else None,'coverageEnd':bars[-1]['at'] if bars else None,
            'observedAt':now_iso(),'partial':partial,'note':'Display history only; not forward-observed execution evidence'}


def execute(db,job,database):
    body=json.loads(job['payload_json']);kind=job['kind'];asset=body.get('asset')
    if kind=='chart':
        result=chart(body)
        with db:
            db.execute('INSERT OR REPLACE INTO crypto_chart_cache VALUES (?,?,?)',(body['key'],canonical(result),now_iso()))
            db.execute("DELETE FROM crypto_chart_cache WHERE datetime(updated_at)<datetime('now','-2 days')")
            db.execute("DELETE FROM workspace_jobs WHERE kind='chart' AND status IN ('succeeded','failed') AND datetime(created_at)<datetime('now','-2 days')")
        return {'points':len(result['bars'])}
    if kind=='publish':
        from .rules import RuleConfig
        row=db.execute('SELECT * FROM workspace_drafts WHERE id=? AND asset=?',(body['draft'],asset)).fetchone()
        if not row:raise ValueError('Draft is unavailable')
        snapshot=body['snapshot']
        config=RuleConfig(**{**json.loads(snapshot['document_json']),'asset':asset})
        version=register_version(db,config,snapshot['name'])
        with db:
            db.execute('INSERT INTO workspace_version_details(version_id,draft_id,parent_version) VALUES (?,?,?) ON CONFLICT(version_id) DO NOTHING',(version,row['id'],snapshot.get('published_version') if snapshot.get('published_version')!=version else None))
            db.execute('UPDATE workspace_drafts SET published_version=? WHERE id=?',(version,row['id']))
        return {'version':version}
    version=db.execute('SELECT * FROM system_versions WHERE id=? AND asset=?',(body['version'],asset)).fetchone()
    if not version:raise ValueError('System version is unavailable')
    if kind=='backtest':
        from .datasets import bitcoin_dataset,stock_dataset,save_dataset
        config=json.loads(version['config_json'])
        data=bitcoin_dataset(body['start'],body['end'],timeframe=config.get('timeframe','1Hour'),canceled=lambda:bool(db.execute('SELECT cancel_requested FROM workspace_jobs WHERE id=?',(job['id'],)).fetchone()[0])) if asset=='bitcoin' else stock_dataset(db)
        data['bars']=[r for r in data['bars'] if instant(body['start'])<=instant(r['at'])<instant(body['end'])]
        if not data['bars']:raise ValueError('No captured bars cover this interval; choose a covered range')
        for key,rows in data.get('benchmarks',{}).items():data['benchmarks'][key]=[r for r in rows if instant(body['start'])<=instant(r['at'])<instant(body['end'])]
        data['manifest'].update(actual_start=data['bars'][0]['at'],actual_end=data['bars'][-1]['at'])
        data['slippage_bps']=5*float(body.get('costMultiplier',1))
        dataset=save_dataset(db,data,Path(str(database)+'.systems-data'))
        with db:db.execute('INSERT INTO system_runs(id,version_id,dataset_id,status,created_at) VALUES (?,?,?,\'queued\',?)',(job['id'],version['id'],dataset,now_iso()))
        return {'run':job['id'],'dataset':dataset}
    config=json.loads(version['config_json']);automated=asset=='bitcoin' and config.get('protocol') in ('bitcoin-automation-v2','visual-rules-v1')
    if kind=='observe':
        if automated:
            if db.execute('SELECT count(*) FROM btc_enrollments WHERE active=1').fetchone()[0]>=5 and not db.execute('SELECT 1 FROM btc_enrollments WHERE version_id=? AND active=1',(version['id'],)).fetchone():raise ValueError('At most five Crypto systems may collect simultaneously')
            with db:db.execute('INSERT INTO btc_enrollments(version_id,enrolled_at) VALUES (?,?) ON CONFLICT(version_id) DO UPDATE SET active=1',(version['id'],now_iso()))
            return {'enrolled':version['id']}
        from .runtime import start_shadow
        old=db.execute('SELECT id FROM system_deployments WHERE version_id=?',(version['id'],)).fetchone()
        return {'deployment':old[0] if old else start_shadow(db,version['id'])}
    if automated:
        if kind=='start_paper':
            allocation=db.execute('SELECT * FROM btc_allocations WHERE version_id=?',(version['id'],)).fetchone()
            q=db.execute('SELECT q.*,e.expires_at,e.budget FROM btc_qualifications q JOIN btc_evaluations e ON e.id=q.evaluation_id WHERE q.version_id=?',(version['id'],)).fetchone()
            if not allocation:raise ValueError('Fund and reconcile the separate Crypto paper account in Account setup before starting')
            if not q or q['status']!='qualified' or instant(q['expires_at'])<=datetime.now(timezone.utc) or float(q['budget'])!=float(allocation['budget']):raise ValueError('Current qualification for this allocation is required')
            account=db.execute('SELECT * FROM btc_accounts WHERE id=?',(allocation['account_id'],)).fetchone()
            enrollment=db.execute('SELECT * FROM btc_enrollments WHERE version_id=?',(version['id'],)).fetchone()
            health=db.execute("SELECT * FROM btc_health WHERE key='account'").fetchone()
            if not enrollment or not enrollment['active'] or allocation['risk_paused'] or not account or account['risk_paused']:raise ValueError('Active observation and an unpaused account are required')
            from datetime import timedelta
            if not health or health['error'] or instant(health['at'])<datetime.now(timezone.utc)-timedelta(minutes=2):raise ValueError('Recent successful account reconciliation is required')
            from .evaluation import forward_ready
            if not forward_ready(db,version['id'],datetime.now(timezone.utc))[0]:raise ValueError('Current forward evidence is required')
            with db:
                db.execute('UPDATE btc_allocations SET started_at=COALESCE(started_at,?) WHERE version_id=?',(now_iso(),version['id']))
                db.execute('UPDATE btc_enrollments SET approved_at=COALESCE(approved_at,?),paused=0 WHERE version_id=?',(now_iso(),version['id']))
        elif kind in ('pause','resume'):
            if not db.execute('SELECT 1 FROM btc_enrollments WHERE version_id=?',(version['id'],)).fetchone():raise ValueError('Start observation before changing paper state')
            a=db.execute('SELECT a.risk_paused,a.started_at,c.risk_paused AS account_risk FROM btc_allocations a JOIN btc_accounts c ON c.id=a.account_id WHERE version_id=?',(version['id'],)).fetchone()
            if kind=='resume' and (not a or not a['started_at'] or a['risk_paused'] or a['account_risk']):raise ValueError('Risk pause or unstarted system requires reviewed account recovery')
            with db:db.execute('UPDATE btc_enrollments SET paused=? WHERE version_id=?',(int(kind=='pause'),version['id']))
        else:raise ValueError('Unsupported account command')
        with db:audit(db,'workspace_'+kind,version['id'],{})
        return {'version':version['id'],'action':kind}
    deployment=db.execute('SELECT * FROM system_deployments WHERE version_id=?',(version['id'],)).fetchone()
    if not deployment:raise ValueError('Start forward observation before requesting paper activation')
    action={'start_paper':'activate','pause':'pause','resume':'resume'}[kind]
    with db:db.execute('INSERT OR IGNORE INTO system_commands(id,deployment_id,action,confirmation,created_at) VALUES (?,?,?,?,?)',(job['id'],deployment['id'],action,deployment['id'],now_iso()))
    return {'command':job['id'],'state':'awaiting trading worker validation'}


def run_workspace(db,database,charts_only=False):
    # Chart and research workers hold separate process locks and disjoint queues.
    scope="kind='chart'" if charts_only else "kind!='chart'"
    with db:db.execute(f"UPDATE workspace_jobs SET status='failed',error='Worker interrupted; retry explicitly',finished_at=? WHERE status='running' AND {scope}",(now_iso(),))
    job=db.execute(f"SELECT * FROM workspace_jobs WHERE status='queued' AND cancel_requested=0 AND {scope} ORDER BY created_at LIMIT 1").fetchone()
    if not job:return
    with db:db.execute("UPDATE workspace_jobs SET status='running',started_at=?,progress=10 WHERE id=?",(now_iso(),job['id']))
    try:
        result=execute(db,job,database)
        canceled=db.execute('SELECT cancel_requested FROM workspace_jobs WHERE id=?',(job['id'],)).fetchone()[0]
        if canceled:
            with db:db.execute('UPDATE system_runs SET cancel_requested=1 WHERE id=?',(job['id'],))
        with db:db.execute('UPDATE workspace_jobs SET status=?,progress=100,result_json=?,finished_at=? WHERE id=?',('canceled' if canceled else 'succeeded',canonical(result),now_iso(),job['id']))
    except Exception as error:
        canceled=db.execute('SELECT cancel_requested FROM workspace_jobs WHERE id=?',(job['id'],)).fetchone()[0]
        with db:db.execute('UPDATE workspace_jobs SET status=?,error=?,finished_at=? WHERE id=?',('canceled' if canceled else 'failed',None if canceled else str(error)[:500],now_iso(),job['id']))
    return job['id']
