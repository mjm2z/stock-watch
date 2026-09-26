"""Versioned analytics over complete execution evidence; never display samples."""
import hashlib
import json

VERSION='net-trades-v1'

def trade_metrics(report,asset):
    if not all(key in report for key in ('fills','starting_cash','ending_equity')):
        return {'version':VERSION,'available':False,'reason':'Complete execution evidence required'}
    fills=report.get('fills',[])
    if report.get('fills_in_full_artifact',len(fills))!=len(fills):
        return {'version':VERSION,'available':False,'reason':'Complete execution artifact required'}
    held={};trades=[]
    for fill in fills:
        symbol=fill['symbol'];q=float(fill['qty']);price=float(fill['price']);fee=float(fill.get('fee',0))
        if fill['side']=='buy':
            p=held.setdefault(symbol,{'quantity':0.,'cost':0.,'spent':0.,'proceeds':0.,'at':fill['at']})
            net=q-fee/price if asset=='bitcoin' else q
            cost=q*price+(fee if asset!='bitcoin' else 0)
            p['quantity']+=net;p['cost']+=cost;p['spent']+=cost
        else:
            p=held.get(symbol)
            if not p or q>p['quantity']+1e-7:
                return {'version':VERSION,'available':False,'reason':'Incomplete or unmatched fills'}
            p['quantity']-=q;p['proceeds']+=q*price-fee
            if p['quantity']<1e-8:
                trades.append({'id':hashlib.sha256(f"{symbol}|{p['at']}|{fill['at']}".encode()).hexdigest(),
                               'symbol':symbol,'entry_at':p['at'],'exit_at':fill['at'],
                               'cost':p['spent'],'pnl':p['proceeds']-p['spent']})
                del held[symbol]
    profits=sum(max(0,t['pnl']) for t in trades);losses=-sum(min(0,t['pnl']) for t in trades)
    winners=[t['pnl'] for t in trades if t['pnl']>0];losers=[t['pnl'] for t in trades if t['pnl']<0]
    realized=sum(t['pnl'] for t in trades)
    net=float(report.get('ending_equity',0))-float(report.get('starting_cash',0))
    return {'version':VERSION,'available':True,'net_pnl':net,'realized_closed_pnl':realized,
            'open_and_partial_pnl':net-realized,'closed_trades':len(trades),'wins':len(winners),
            'losses':len(losers),'flat':len(trades)-len(winners)-len(losers),
            'profit_factor':profits/losses if losses else None,
            'profit_factor_note':'No losing closed trades' if not losses else None,
            'average_trade':realized/len(trades) if trades else None,
            'average_win':sum(winners)/len(winners) if winners else None,
            'average_loss':sum(losers)/len(losers) if losers else None,'trades':trades}

def enrich(result,asset):
    for key in ('base','double_cost','validation','test'):
        if isinstance(result.get(key),dict):result[key]['metrics']=trade_metrics(result[key],asset)
    for fold in result.get('folds',[]):enrich(fold,asset)
    return result

def backfill(db,limit=5):
    from pathlib import Path
    from .research import now_iso
    from .engine import canonical
    rows=db.execute('''SELECT r.*,v.asset,d.path FROM system_runs r JOIN system_versions v ON v.id=r.version_id
        JOIN system_datasets d ON d.id=r.dataset_id LEFT JOIN research_metrics m ON m.run_id=r.id
        WHERE r.status='succeeded' AND m.run_id IS NULL ORDER BY r.created_at LIMIT ?''',(limit,)).fetchall()
    for row in rows:
        result=json.loads(row['result_json']);path=Path(row['path']).parent/(row['id']+'.result.json')
        if path.exists() and result.get('result_artifact_sha256'):
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()==result['result_artifact_sha256']:result=json.loads(raw)
        metrics=trade_metrics(result.get('base',{}),row['asset'])
        with db:db.execute('INSERT OR IGNORE INTO research_metrics VALUES (?,?,?,?)',(row['id'],VERSION,canonical(metrics),now_iso()))
