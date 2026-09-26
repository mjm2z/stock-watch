"""Bounded, resumable historical research. This module never submits orders."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
from zoneinfo import ZoneInfo
from urllib.request import urlopen,Request
import xml.etree.ElementTree as ET
from .engine import canonical,instant,digest,replay
from .research import now_iso,register_version
from .automation_config import load_config
from .reporting import trade_metrics,backfill
from .timeframes import deadline,evidence_expiry

PROFILES=('base','double_fees','double_execution','delayed_partial','combined')

def policy(db):return db.execute('SELECT * FROM research_policies ORDER BY id DESC LIMIT 1').fetchone()

def event(db,asset,kind,entity,payload):
    with db:db.execute('INSERT INTO research_events(at,asset,kind,entity_id,payload_json) VALUES (?,?,?,?,?)',(now_iso(),asset,kind,entity,canonical(payload)))

def templates(asset):
    from .rules import RuleConfig
    def group(op,left,right):return {'op':'all','conditions':[{'op':op,'left':left,'right':right}]}
    for name,kind,baseline,values in [('Trend','sma',200,(160,240)),('Breakout','prior_high',20,(16,24)),('RSI reversal','rsi',30,(25,35))]:
        for value in values:
            if kind=='rsi':
                entry=group('crosses_above',{'kind':'rsi','period':14},{'kind':'number','value':value})
                exit=group('crosses_below',{'kind':'rsi','period':14},{'kind':'number','value':70})
            else:
                entry=group('gt',{'kind':'close'},{'kind':kind,'period':value})
                exit=group('lt',{'kind':'close'},{'kind':'sma' if kind=='sma' else 'prior_low','period':value if kind=='sma' else 10})
            # Holding/risk defaults are explicit research configurations, not edits to existing systems.
            config=RuleConfig(asset,entry,exit,timeframe='1Day',allocation=.25,holding_count=30,holding_unit='days',stop_loss=.1,take_profit=.2)
            yield f'{name} {value} · discovery',config,{'family':name,'parameter':kind,'baseline':baseline,'value':value}

def proposals(db):
    url='https://export.arxiv.org/api/query?search_query=%28cat:q-fin.TR%20OR%20cat:q-fin.PM%29%20AND%20%28all:momentum%20OR%20all:trend%20OR%20all:reversion%29&sortBy=submittedDate&sortOrder=descending&max_results=10'
    try:
        with urlopen(Request(url,headers={'User-Agent':'StockWatchResearch/1.0 (personal research)'}),timeout=20) as r:raw=r.read(512_001)
        if len(raw)>512_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('Unsupported proposal feed')
        root=ET.fromstring(raw);ns={'a':'http://www.w3.org/2005/Atom'}
        with db:
            for row in root.findall('a:entry',ns):
                link=row.findtext('a:id','',ns)
                if not link.startswith(('https://arxiv.org/abs/','http://arxiv.org/abs/')):continue
                identifier=link.split('/abs/')[-1];title=' '.join(row.findtext('a:title','',ns).split())[:300]
                excerpt=' '.join(row.findtext('a:summary','',ns).split())[:900]
                db.execute('INSERT OR IGNORE INTO research_proposals(id,url,title,excerpt,published_at,retrieved_at) VALUES (?,?,?,?,?,?)',
                    (identifier,'https://arxiv.org/abs/'+identifier,title,excerpt,row.findtext('a:published','',ns),now_iso()))
        event(db,'all','proposal_collection',None,{'status':'completed'})
    except Exception as error:event(db,'all','proposal_collection',None,{'status':'failed','reason':str(error)[:300]})

def schedule(db,now):
    p=policy(db)
    if not p['discovery_enabled']:return None
    day=now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    if db.execute('SELECT 1 FROM discovery_batches WHERE id=?',(day,)).fetchone():return day
    with db:db.execute('INSERT INTO discovery_batches(id,created_at,updated_at) VALUES (?,?,?)',(day,now.isoformat(),now.isoformat()))
    # Resume previous unfinished work before adding equivalent new candidates.
    for asset in ('bitcoin','stocks'):
        for name,config,change in templates(asset):
            version=register_version(db,config,name)
            old=db.execute("SELECT 1 FROM discovery_trials WHERE version_id=? AND (status IN ('queued','running') OR (policy_id=? AND datetime(created_at)>datetime(?,'-7 days')))",(version,p['id'],now.isoformat())).fetchone()
            if old:continue
            with db:
                db.execute('INSERT OR IGNORE INTO research_lineage VALUES (?,NULL,NULL,?,?,?)',(version,'Reviewed trend/breakout/RSI family; single-parameter variation',canonical(change),now.isoformat()))
                db.execute('INSERT INTO discovery_trials(id,batch_id,version_id,asset,policy_id,budget,created_at) VALUES (?,?,?,?,?,?,?)',
                    (uuid.uuid4().hex,day,version,asset,p['id'],p['sleeve'] if asset=='bitcoin' else '300',now.isoformat()))
    proposals(db)
    return day

def prepare_data(db,trial,database,canceled=lambda:False):
    from .datasets import bitcoin_dataset,stock_dataset,save_dataset
    config=load_config(json.loads(db.execute('SELECT config_json FROM system_versions WHERE id=?',(trial['version_id'],)).fetchone()[0]))
    cutoff=instant(trial['created_at']).replace(hour=0,minute=0,second=0,microsecond=0)
    first=cutoff-timedelta(days=1460)
    # All daily candidates in the same batch share one frozen dataset.
    existing=db.execute("SELECT dataset_id FROM discovery_trials WHERE batch_id=? AND asset=? AND dataset_id IS NOT NULL AND version_id IN (SELECT id FROM system_versions WHERE json_extract(config_json,'$.timeframe')=?) LIMIT 1",(trial['batch_id'],trial['asset'],config.timeframe)).fetchone()
    if existing:return existing[0]
    data=bitcoin_dataset(first.isoformat(),cutoff.isoformat(),timeframe=config.timeframe,canceled=canceled) if trial['asset']=='bitcoin' else stock_dataset(db)
    return save_dataset(db,data,Path(str(database)+'.systems-data'))

def windows(config,data):
    end=instant(data['bars'][-1]['at'])
    holding=deadline(end,config.holding_count,config.holding_unit)-end
    length=max(timedelta(days=90),2*holding)
    stride=length/4
    values=[(end-length-stride*(19-i),end-stride*(19-i)) for i in range(20)]
    # Reserve actual indicator warmup rather than accepting a short silent test.
    from .timeframes import advance
    if instant(data['bars'][0]['at'])>advance(values[0][0],config.timeframe,-252):
        raise ValueError('Insufficient history for 20 windows and indicator warmup; shorten holding duration or collect more history')
    return values

def scenario(config,data,start,end,profile,budget,canceled=lambda:False):
    from .reporting import trade_metrics
    source=deepcopy(data)
    if profile in ('delayed_partial','combined'):
        # A one-bar delayed open and 50% displayed liquidity are explicitly synthetic stress.
        rows=source['bars'];by_symbol={}
        for row in rows:by_symbol.setdefault(row['symbol'],[]).append(row)
        for series in by_symbol.values():
            for a,b in zip(series,series[1:]):
                if b.get('quote'):
                    a['quote']=dict(b['quote']);capacity=float(b['quote']['ask'] or 1)
                    a['quote']['ask_size']=float(budget)*config.allocation/capacity/2
                    a['quote']['bid_size']=float(budget)*config.allocation/capacity/2
                else:a.pop('quote',None)
            series[-1].pop('quote',None)
    result=replay(config,source,start=start,end=end,starting_cash=float(budget),canceled=canceled,
                  fee_multiplier=2 if profile in ('double_fees','combined') else 1,
                  execution_multiplier=2 if profile in ('double_execution','combined') else 1)
    metrics=trade_metrics(result,config.asset)
    from .timeframes import advance
    selected=[r for r in source['bars'] if instant(start)<=instant(r['at'])<=instant(end)]
    bad=not selected or any('Missing hourly bars' in w for w in result['warnings'])
    if config.asset=='bitcoin':
        bad=bad or any(advance(instant(a['at']),config.timeframe)!=instant(b['at']) for a,b in zip(selected,selected[1:]))
    if config.asset=='stocks':
        # Unknown corporate actions cannot support favorable assessment.
        bad=bad or not data['manifest'].get('corporate_actions_verified')
    return {'net_return':result['net_return'],'drawdown':-result['maximum_drawdown'],
            'valid':not bad and metrics['available'],'closed_trades':result['closed_trades'],
            'trades':metrics.get('trades',[]),'warnings':result['warnings'],
            'metrics':{k:v for k,v in metrics.items() if k!='trades'},'risk_paused':result['risk_paused']}

def summarize(rows,threshold):
    values=[{**json.loads(r['result_json']),'profile':r['profile'],'start':r['starts_at'],'end':r['ends_at']} for r in rows]
    base=[r for r in values if r['profile']=='base'];unique={t['id']:t for r in base for t in r['trades']}
    independent=0;last=None
    for r in sorted(base,key=lambda r:r['start']):
        if last is None or instant(r['start'])>=instant(last):independent+=1;last=r['end']
    passed=sum(r['valid'] and r['net_return']>0 and r['drawdown']<=.1 for r in values)
    reasons=[]
    if len(values)!=100 or any(not r['valid'] for r in values):reasons.append('All 100 scenarios require valid coverage and corporate-action treatment')
    if passed<100*threshold-1e-8:reasons.append(f'{passed}/100 scenarios pass; {threshold:.0%} required')
    if len(unique)<30:reasons.append(f'{len(unique)}/30 unique closed trades')
    if independent<5:reasons.append(f'{independent}/5 independent windows')
    from statistics import median
    if not base or median(r['net_return'] for r in base)<=0:reasons.append('Median base return is not positive')
    for profile in PROFILES:
        group=[r for r in values if r['profile']==profile]
        if not group or sum(r['net_return'] for r in group)/len(group)<=0:reasons.append(profile+': nonpositive mean return')
        if any(r['drawdown']>.1 for r in group):reasons.append(profile+': exceeds 10% drawdown')
    return {'protocol':'bounded-discovery-v1','passed':not reasons,'scenario_count':len(values),'passing_scenarios':passed,'scenario_pass_rate':passed/100,
            'unique_trades':len(unique),'independent_windows':independent,
            'trade_win_rate':sum(t['pnl']>0 for t in unique.values())/len(unique) if unique else None,
            'reasons':reasons,'evidence':'experimental_historical','forward_validated':False,
            'limitation':'Overlapping windows and repeated cost profiles are not independent tests; daily execution is modeled.'}

def run(db,database,seconds=1800,now=None):
    began=time.monotonic()
    now=now or datetime.now(timezone.utc);batch=schedule(db,now)
    if not batch:return
    used=db.execute('SELECT consumed_seconds FROM discovery_batches WHERE id=?',(batch,)).fetchone()[0]
    stop=began+max(0,min(seconds,1800-used))
    from .automation_data import health
    try:
        backfill(db)
        while time.monotonic()<stop:
            health(db,'discovery',datetime.now(timezone.utc))
            if not policy(db)['discovery_enabled']:break
            if db.execute("SELECT 1 FROM workspace_jobs WHERE kind!='chart' AND status IN ('queued','running') LIMIT 1").fetchone() or db.execute("SELECT 1 FROM system_runs WHERE status IN ('queued','running') LIMIT 1").fetchone():break
            trial=db.execute("SELECT * FROM discovery_trials WHERE status IN ('queued','running') ORDER BY CASE source WHEN 'operator' THEN 0 ELSE 1 END,created_at,id LIMIT 1").fetchone()
            if not trial:break
            try:
                with db:db.execute("UPDATE discovery_trials SET status='running',heartbeat_at=?,stage='Preparing frozen data' WHERE id=?",(now_iso(),trial['id']))
                dataset=trial['dataset_id'] or prepare_data(db,trial,database,lambda:time.monotonic()>=stop)
                cached=db.execute("SELECT * FROM discovery_trials WHERE version_id=? AND dataset_id=? AND policy_id=? AND budget=? AND id!=?",(trial['version_id'],dataset,trial['policy_id'],trial['budget'],trial['id'])).fetchone()
                if cached:
                    if cached['status']!='completed':raise ValueError('Equivalent dataset evaluation already exists: '+cached['id'])
                    with db:
                        db.execute("UPDATE discovery_trials SET status='completed',stage='Reused identical frozen evidence',finished_at=?,expires_at=?,result_json=? WHERE id=?",(now_iso(),cached['expires_at'],cached['result_json'],trial['id']))
                        db.execute('INSERT OR IGNORE INTO discovery_scenarios SELECT ?,window_index,profile,starts_at,ends_at,result_json FROM discovery_scenarios WHERE trial_id=?',(trial['id'],cached['id']))
                    continue
                with db:db.execute('UPDATE discovery_trials SET dataset_id=? WHERE id=?',(dataset,trial['id']))
                record=db.execute('SELECT * FROM system_datasets WHERE id=?',(dataset,)).fetchone();raw=Path(record['path']).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('Dataset integrity failed')
                data=json.loads(raw);config=load_config(json.loads(db.execute('SELECT config_json FROM system_versions WHERE id=?',(trial['version_id'],)).fetchone()[0]))
                p=db.execute('SELECT * FROM research_policies WHERE id=?',(trial['policy_id'],)).fetchone()
                finished=db.execute('SELECT COUNT(*) FROM discovery_scenarios WHERE trial_id=?',(trial['id'],)).fetchone()[0]
                for i,(start,end) in enumerate(windows(config,data)):
                    for profile in PROFILES:
                        if time.monotonic()>=stop:raise InterruptedError('Nightly budget reached; remaining scenarios resume next batch')
                        if db.execute('SELECT 1 FROM discovery_scenarios WHERE trial_id=? AND window_index=? AND profile=?',(trial['id'],i,profile)).fetchone():continue
                        with db:db.execute('UPDATE discovery_trials SET stage=?,heartbeat_at=? WHERE id=?',(f'Evaluating scenario {finished+1}/100',now_iso(),trial['id']))
                        result=scenario(config,data,start.isoformat(),end.isoformat(),profile,trial['budget'],lambda:time.monotonic()>=stop)
                        with db:db.execute('INSERT INTO discovery_scenarios VALUES (?,?,?,?,?,?)',(trial['id'],i,profile,start.isoformat(),end.isoformat(),canonical(result)))
                        finished+=1
                summary=summarize(db.execute('SELECT * FROM discovery_scenarios WHERE trial_id=?',(trial['id'],)).fetchall(),p['threshold'])
                current=datetime.now(timezone.utc)
                with db:db.execute("UPDATE discovery_trials SET status='completed',stage='Evaluation complete',finished_at=?,expires_at=?,result_json=? WHERE id=?",(current.isoformat(),evidence_expiry(current,config.timeframe).isoformat(),canonical(summary),trial['id']))
                event(db,trial['asset'],'discovery_result',trial['id'],summary)
                if summary['passed']:
                    with db:
                        if trial['asset']=='bitcoin' and db.execute('SELECT COUNT(*) FROM btc_enrollments WHERE active=1').fetchone()[0]<5:
                            db.execute('INSERT OR IGNORE INTO btc_enrollments(version_id,enrolled_at) VALUES (?,?)',(trial['version_id'],now_iso()))
                        elif trial['asset']=='stocks' and db.execute("SELECT COUNT(*) FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE v.asset='stocks' AND d.mode='shadow'").fetchone()[0]<5:
                            db.execute("INSERT OR IGNORE INTO system_deployments(id,version_id,mode,started_at) VALUES (?,?,'shadow',?)",('discovery-'+trial['version_id'],trial['version_id'],now_iso()))
            except InterruptedError:break
            except Exception as error:
                with db:db.execute("UPDATE discovery_trials SET status='blocked',stage='Review required',error=?,finished_at=? WHERE id=?",(str(error)[:500],now_iso(),trial['id']))
                event(db,trial['asset'],'discovery_blocked',trial['id'],{'reason':str(error)[:500]})
    finally:
        elapsed=time.monotonic()-began
        with db:db.execute("UPDATE discovery_batches SET consumed_seconds=consumed_seconds+?,updated_at=?,status='checkpointed' WHERE id=?",(elapsed,now_iso(),batch))
        health(db,'discovery',datetime.now(timezone.utc))
