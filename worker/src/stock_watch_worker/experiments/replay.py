"""Prospective evidence replay using the production engine and a simulated broker.

No network methods exist on this adapter. Captured quotes determine fills after
submission, with modeled fees explicitly separated from broker observations.
"""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
from ..database import connect, apply_migrations
from . import evidence
from .model import canonical, config, digest, instant, stamp, money
from .store import register
from .engine import tick

class ReplayBroker:
    def __init__(self,market,plan,now,slippage='0.001'):
        self.market=market; self.plan=plan; self.asset=plan['asset']; self.now=now
        self.orders={}; self.cash=money(1000); self.holdings={}; self.events=[]; self.slippage=money(slippage)
    def account(self): return {'id':self.plan['account_id'],'cash':str(self.cash),'status':'ACTIVE','currency':'USD'}
    def positions(self): return [{'symbol':s,'qty':str(q)} for s,q in self.holdings.items() if q>0]
    def open_orders(self): return [r for r in self.orders.values() if r['status'] not in ('filled','canceled')]
    def activities(self,after): return [r for r in self.events if instant(r.get('transaction_time') or r['date'])>=instant(after)]
    def execution_check(self,request,account): return self.now,self.account()
    def execution_quote(self,symbol): return evidence.quote(self.market,self.plan['versions'][0],symbol,self.now)
    def submit(self,request):
        row={**request,'id':'sim-'+request['client_order_id'],'status':'accepted','filled_qty':'0','filled_avg_price':None,'submitted_at':stamp(self.now)}
        self.orders[request['client_order_id']]=row; return dict(row)
    def cancel(self,key):
        for r in self.orders.values():
            if r['id']==key and r['status']!='filled': r['status']='canceled'
    def lookup(self,key):
        row=self.orders.get(key)
        if not row: return None
        if row['status']!='accepted' or self.now<=instant(row['submitted_at']): return dict(row)
        try: q=evidence.quote(self.market,self.plan['versions'][0],row['symbol'],self.now)
        except ValueError: return dict(row)
        if instant(q['t'])<=instant(row['submitted_at']): return dict(row)
        price=money(q['ap'] if row['side']=='buy' else q['bp'])*(1+self.slippage*(1 if row['side']=='buy' else -1))
        if row['type']=='limit' and ((row['side']=='buy' and price>money(row['limit_price'])) or (row['side']=='sell' and price<money(row['limit_price']))): return dict(row)
        qty=money(row['qty']); notional=qty*price; sign=1 if row['side']=='buy' else -1
        self.cash-=notional*sign; self.holdings[row['symbol']]=self.holdings.get(row['symbol'],money(0))+qty*sign
        row.update(status='filled',filled_qty=str(qty),filled_avg_price=str(price),filled_at=stamp(self.now),updated_at=stamp(self.now))
        self.events.append({'activity_type':'FILL','id':'fill-'+key,'order_id':row['id'],'transaction_time':stamp(self.now),'symbol':row['symbol'],'side':row['side'],'qty':str(qty),'price':str(price)})
        if self.asset=='bitcoin':
            feeqty=qty*money('.0025') if sign==1 else money(0); feecash=notional*money('.0025') if sign==-1 else money(0)
            self.holdings[row['symbol']]-=feeqty; self.cash-=feecash
            self.events.append({'activity_type':'CFEE','id':'fee-'+key,'order_id':row['id'],'date':stamp(self.now),'symbol':'BTC' if feeqty else 'USD','qty':str(feeqty),'net_amount':str(-feecash),'status':'executed'})
        return dict(row)

def execute(db,job,database):
    body=json.loads(job['payload_json']); batch=db.execute('SELECT * FROM experiment_batches WHERE id=? AND asset=?',(body['batch_id'],body['asset'])).fetchone()
    if not batch: raise ValueError('Frozen batch unavailable')
    start,end=instant(body['start']),instant(body['end'])
    if not timedelta(0)<end-start<=timedelta(days=14): raise ValueError('Replay window exceeds 14 days')
    storage=Path(str(database)+'.systems-data'); storage.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.experiment-staging-',dir=storage) as temporary:
        root=Path(temporary); market=evidence.connect(root/'evidence.db'); sim=connect(root/'replay.db'); apply_migrations(sim)
        # Only disposable simulations use relaxed fsync. Production ledgers and
        # source evidence retain their configured durability.
        sim.execute('PRAGMA synchronous=OFF'); market.execute('PRAGMA synchronous=OFF')
        try:
            source=Path(str(database)+'.experiment-evidence.db').resolve().as_uri()+'?mode=ro'
            market.execute('ATTACH DATABASE ? AS captured',(source,))
            # Bounded snapshot: all bar revisions and one last quote per 5-second
            # interval. Keep real receipt times; no reconstructed quotes or volume.
            with market:
                market.execute('INSERT INTO bars SELECT * FROM captured.bars WHERE asset=? AND at>=? AND at<? AND observed<?',(body['asset'],stamp(start-timedelta(days=10)),stamp(end),stamp(end)))
                market.execute('''INSERT INTO feed_events SELECT id,asset,feed,symbol,kind,at,observed,payload FROM
                    (SELECT *,ROW_NUMBER() OVER(PARTITION BY symbol,kind,CAST(unixepoch(observed)/5 AS INTEGER) ORDER BY observed DESC,id DESC) n
                    FROM captured.feed_events WHERE asset=? AND observed>=? AND observed<? AND kind='q') WHERE n=1''',(body['asset'],stamp(start),stamp(end)))
                market.execute('INSERT INTO news SELECT * FROM captured.news WHERE observed>=? AND observed<?',(stamp(start-timedelta(hours=1)),stamp(end)))
                market.execute('INSERT INTO health_events SELECT * FROM captured.health_events WHERE at>=? AND at<?',(stamp(start-timedelta(minutes=5)),stamp(end)))
            market.execute('DETACH DATABASE captured')
            plan=json.loads(batch['plan_json']); plan.update(created=stamp(start),expires=stamp(end),account_id='replay-paper')
            batch_id='replay-'+job['id']
            with sim:
                sim.execute("INSERT INTO experiment_batches(id,asset,revision,plan_json,created,expires,account_id,approved,status) VALUES (?,?,?,?,?,?,?,?,'active')",
                    (batch_id,body['asset'],digest(plan),canonical(plan),stamp(start),stamp(end),'replay-paper',stamp(start)))
                for cfg in plan['versions']:
                    version=register(sim,cfg,start)
                    sim.execute("INSERT INTO experiment_instances(id,batch_id,version_id,budget,cash,state) VALUES (?,?,?,?,?,'ready')",(digest({'batch':batch_id,'version':version}),batch_id,version,cfg['allocation'],cfg['allocation']))
                sim.executemany('INSERT INTO experiment_calendar VALUES (?,?,?,?,?)',[tuple(r) for r in db.execute('SELECT * FROM experiment_calendar WHERE date>=? AND date<=?',((start-timedelta(days=10)).date().isoformat(),end.date().isoformat()))])
            broker=ReplayBroker(market,plan,start); curves={}; count=0
            times=market.execute("SELECT MAX(observed) at FROM feed_events WHERE kind='q' GROUP BY CAST(unixepoch(observed)/5 AS INTEGER) ORDER BY at")
            for value in times:
                now=instant(value['at']); broker.now=now
                if count%100==0 and db.execute('SELECT cancel_requested FROM workspace_jobs WHERE id=?',(job['id'],)).fetchone()[0]: raise InterruptedError('Replay canceled')
                # News health is not reconstructed: require a captured news item
                # or explicitly mark the news arm unavailable in this replay.
                tick(sim,market,broker,body['asset'],now); count+=1
                if now.minute%5==0 and now.second>=35:
                    for row in sim.execute('SELECT * FROM experiment_instances'):
                        equity=money(row['cash']); exposure=money(0)
                        for p in sim.execute('SELECT * FROM experiment_positions WHERE instance_id=?',(row['id'],)):
                            try: value=money(p['quantity'])*money(evidence.quote(market,plan['versions'][0],p['symbol'],now)['bp'])
                            except ValueError: value=money(p['cost'])
                            equity+=value; exposure+=value
                        curves.setdefault(row['id'],[]).append((stamp(now),str(equity),str(exposure)))
            if not count: raise ValueError('No captured execution quotes cover this period')
            metrics=[]
            for row in sim.execute('SELECT i.*,v.family FROM experiment_instances i JOIN experiment_versions v ON v.id=i.version_id'):
                curve=curves.get(row['id'],[]); peak=money(row['budget']); drawdown=money(0)
                for _,value,_ in curve:
                    peak=max(peak,money(value)); drawdown=min(drawdown,money(value)/peak-1)
                fills=sim.execute('SELECT f.*,o.side,o.symbol FROM experiment_fills f JOIN experiment_orders o ON o.id=f.order_id WHERE o.instance_id=? ORDER BY f.at,f.id',(row['id'],)).fetchall()
                entries={}; holding=[]; previous_side={}
                for fill in fills:
                    if fill['side']=='buy' and previous_side.get(fill['symbol'])!='buy': entries[fill['symbol']]=instant(fill['at'])
                    elif fill['side']=='sell' and fill['symbol'] in entries: holding.append((instant(fill['at'])-entries[fill['symbol']]).total_seconds()/60)
                    previous_side[fill['symbol']]=fill['side']
                end_equity=money(curve[-1][1]) if curve else money(row['cash'])
                decisions=sim.execute('SELECT count(*) FROM experiment_decisions WHERE instance_id=?',(row['id'],)).fetchone()[0]
                metrics.append({'family':row['family'],'ranked':row['family']!='control','allocated_return':float(end_equity/money(row['budget'])-1),
                    'maximum_drawdown':float(drawdown),'turnover':float(sum((money(f['notional']) for f in fills),money(0))/money(row['budget'])),
                    'mean_sampled_exposure':float(sum((money(v[2]) for v in curve),money(0))/max(1,len(curve))/money(row['budget'])),
                    'fills':len(fills),'decisions':decisions,'inactivity_fraction':1-len(fills)/max(1,decisions),
                    'mean_exit_holding_minutes':sum(holding)/len(holding) if holding else None,
                    'modeled_fees_usd':str(sum((money(f['cash'])+money(f['quantity'])*money(f['filled_notional'])/money(f['filled_qty']) for f in sim.execute('SELECT f.cash,f.quantity,o.filled_notional,o.filled_qty FROM experiment_fees f JOIN experiment_orders o ON o.id=f.order_id WHERE o.instance_id=? AND CAST(o.filled_qty AS REAL)>0',(row['id'],))),money(0)))})
            returns=[]
            for symbol in plan['versions'][0]['universe']:
                first_row=market.execute("SELECT payload FROM feed_events WHERE symbol=? AND kind='q' ORDER BY at LIMIT 1",(symbol,)).fetchone()
                last_row=market.execute("SELECT payload FROM feed_events WHERE symbol=? AND kind='q' ORDER BY at DESC LIMIT 1",(symbol,)).fetchone()
                if not first_row or not last_row: continue
                first,last=json.loads(first_row[0]),json.loads(last_row[0])
                if (instant(first['t'])-start).total_seconds()>300 or (end-instant(last['t'])).total_seconds()>300: continue
                returns.append(float((money(last['bp'])+money(last['ap']))/(money(first['bp'])+money(first['ap']))-1))
            benchmark={'available':len(returns)==len(plan['versions'][0]['universe']),'symbols_covered':len(returns),
                'return':sum(returns)/len(returns) if returns else None,'allocation':'Equal weight on the same $200 allocation',
                'note':'Quote midpoint price return; excludes dividends and transaction costs'}
            by_family={r['family']:r for r in metrics}
            summary={'protocol':'intraday-replay-v1','provenance':'Captured prospective bars/news/quotes; simulated fills, 10 bp slippage and 25 bp crypto fees',
                'batch_revision':batch['revision'],'start':stamp(start),'end':stamp(end),'ticks':count,'metrics':metrics,
                'benchmarks':{'cash_return':0,'buy_and_hold':benchmark},
                'news_ablation':{'baseline':'breakout','news_filter':'news_breakout','return_difference':by_family['news_breakout']['allocated_return']-by_family['breakout']['allocated_return'],
                    'note':'Shared account capacity can affect fills; this is an exploratory comparison, not an isolated causal estimate'},
                'limitations':['Five-second quote sampling can miss brief prices.','Only retained prospective quote coverage is replayed.','News-dependent entries require captured feed-health evidence.','No profitability qualification is granted.']}
        finally:
            sim.execute('PRAGMA wal_checkpoint(TRUNCATE)'); sim.close()
            market.execute('PRAGMA wal_checkpoint(TRUNCATE)'); market.close()
        artifacts={}
        for name in ('evidence','replay'):
            file=root/(name+'.db')
            with file.open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
            target=storage/(sha+'.experiment-'+name+'.db')
            if not target.exists(): file.rename(target)
            artifacts[name]=target.name
        summary['artifacts']=artifacts
        raw=canonical(summary).encode(); sha=hashlib.sha256(raw).hexdigest(); target=storage/(sha+'.experiment-replay.json')
        if not target.exists(): target.write_bytes(raw)
        return {**summary,'artifact_sha256':sha}
