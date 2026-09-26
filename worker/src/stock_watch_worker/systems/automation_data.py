"""Independent collection/backfill and capital-constrained forward observation."""
from datetime import timedelta
import json
from urllib.parse import urlencode
from .engine import canonical, decision, instant
from .evaluation import config_for, windows
from .history import collect, import_rows, latest_bars
from .timeframes import advance, boundary, deadline


def health(db,key,now,error=None):
    with db: db.execute('INSERT INTO btc_health VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET at=excluded.at,error=excluded.error',(key,now.isoformat(),error))


def collect_forward(db,history,broker,now):
    rows=db.execute('SELECT * FROM btc_enrollments WHERE active=1 ORDER BY enrolled_at').fetchall()
    if not rows: return
    configs=[config_for(db,row['version_id']) for row in rows]
    try:
        quote=collect(history,broker,configs,now)
        health(db,'data',now)
    except Exception as error:
        health(db,'data',now,str(error)[:500]); raise
    for enrollment,config in zip(rows,configs):
        try:
            bars=latest_bars(history,config,now)
            state=json.loads(enrollment['state_json'])
            cash=float(state.get('cash',300)); qty=float(state.get('quantity',0))
            bid,ask=float(quote['bp'])*.9995,float(quote['ap'])*1.0005
            equity=cash+qty*bid*.9975; peak=max(float(state.get('peak',300)),equity)
            risk=bool(state.get('risk')) or equity/peak<=.9
            due=bool(qty and now>=instant(state['exit_due_at']))
            pending=state.get('pending')
            if qty and (risk or due): pending={'side':'sell','at':now.isoformat(),'reason':'risk' if risk else 'deadline'} if not pending or pending['side']!='sell' else pending
            # Strictly subsequent quote and bounded entry validity.
            if pending and instant(quote['t'])>instant(pending['at']):
                side=pending['side']; size=float(quote.get('as' if side=='buy' else 'bs') or 0)
                if side=='buy' and not risk and (now-instant(pending['at'])).total_seconds()<=90:
                    gross=min(cash/ask,equity*config.allocation/ask,size)
                    if gross>0:
                        cash-=gross*ask; qty+=gross*.9975
                        state['exit_due_at']=deadline(now,config.holding_count,config.holding_unit).isoformat()
                elif side=='sell':
                    fill=min(qty,size); cash+=fill*bid*.9975; qty-=fill
                    if qty>1e-10: pending={'side':'sell','at':now.isoformat(),'reason':pending.get('reason','signal')}
                    else: qty=0; pending=None
                if side=='buy': pending=None
            bar=bars[-1]['at']
            if state.get('last_decision')!=bar:
                action,reason=decision(config,bars,qty>0)
                if not pending and action!='hold' and not (action=='buy' and risk): pending={'side':action,'at':now.isoformat(),'reason':reason}
                state['last_decision']=bar
            state.update(cash=cash,quantity=qty,peak=peak,risk=risk,pending=pending)
            equity=cash+qty*bid*.9975
            with db:
                db.execute('UPDATE btc_enrollments SET state_json=? WHERE version_id=?',(canonical(state),enrollment['version_id']))
                # Minute sampling bounds main DB growth; decision events remain in state.
                stamp=now.replace(second=0,microsecond=0).isoformat()
                db.execute('INSERT OR IGNORE INTO btc_forward VALUES (?,?,?,?)',(enrollment['version_id'],stamp,equity,canonical({'cash':cash,'quantity':qty,'drawdown':1-equity/peak,'risk':risk,'execution':'observed subsequent bid/ask, 5bps slippage, 25bps fee'})))
        except Exception as error:
            health(db,'forward:'+enrollment['version_id'],now,str(error)[:500])
        else: health(db,'forward:'+enrollment['version_id'],now)


def backfill_one(db,history,broker,now):
    """One provider page per invocation; repeatable cursor, no all-history JSON."""
    for row in db.execute('SELECT version_id FROM btc_enrollments WHERE active=1 ORDER BY enrolled_at').fetchall():
        config=config_for(db,row[0]); frame=config.timeframe
        key='backfill:'+row[0]
        state=history.execute('SELECT value FROM collection_state WHERE key=?',(key,)).fetchone()
        if state:
            cursor=json.loads(state[0])
            if cursor['done']: continue
        else:
            start=advance(windows(config,now)[0][0],frame,-max(config.slow,config.entry)-2)
            cursor={'start':start.isoformat(),'end':boundary(now,frame).isoformat(),'token':None,'done':False}
        params={'symbols':'BTC/USD','timeframe':frame,'start':cursor['start'],'end':cursor['end'],'limit':10000,'sort':'asc'}
        if cursor['token']: params['page_token']=cursor['token']
        result=broker.request('GET','/v1beta3/crypto/us/bars?'+urlencode(params),data=True)
        rows=[]
        for bar in result.get('bars',{}).get('BTC/USD',[]):
            close=advance(instant(bar['t']),frame)
            if close>instant(cursor['end']): continue
            # Do not overwrite a prospectively captured observation.
            if history.execute('SELECT 1 FROM bars WHERE timeframe=? AND at=? LIMIT 1',(frame,close.isoformat())).fetchone(): continue
            rows.append({'symbol':'BTC/USD','at':close.isoformat(),'available_at':close.isoformat(),'open':bar['o'],'high':bar['h'],'low':bar['l'],'close':bar['c'],'volume':bar['v']})
        import_rows(history,frame,rows,now.isoformat(),historical=True)
        cursor['token']=result.get('next_page_token'); cursor['done']=not bool(cursor['token'])
        with history: history.execute('INSERT INTO collection_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,canonical(cursor)))
        health(db,'backfill',now)
        return True
    return False
