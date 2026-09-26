"""Free-first dataset builders. Bar-derived execution stays explicitly approximate."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from ..http import UrllibTransport, require_success
from .engine import canonical, instant
from .research import register_dataset


def bitcoin_dataset(start, end, transport=None, timeframe="1Hour", canceled=lambda:False):
    from .timeframes import advance, TIMEFRAMES
    if timeframe not in TIMEFRAMES: raise ValueError("Unsupported timeframe")
    start_time,end_time = instant(start),instant(end)
    if start_time >= end_time or end_time > datetime.now(timezone.utc):
        raise ValueError('Choose an ordered historical UTC interval')
    transport = transport or UrllibTransport()
    prefix='BITCOIN_ALPACA' if os.environ.get('BITCOIN_ALPACA_API_KEY_ID') and os.environ.get('BITCOIN_ALPACA_API_SECRET_KEY') else 'ALPACA'
    headers={'APCA-API-KEY-ID':os.environ.get(prefix+'_API_KEY_ID',''),'APCA-API-SECRET-KEY':os.environ.get(prefix+'_API_SECRET_KEY','')}
    if not all(headers.values()): raise ValueError('Alpaca market-data credentials are required')
    bars,token = [],None
    for _ in range(12):
        if canceled():raise InterruptedError('Backtest canceled during data collection')
        params={'symbols':'BTC/USD','timeframe':timeframe,'start':start,'end':end,'limit':10000,'sort':'asc'}
        if token: params['page_token']=token
        response=transport.request('GET','https://data.alpaca.markets/v1beta3/crypto/us/bars?'+urlencode(params),headers=headers,timeout=30)
        payload=require_success('alpaca-crypto-data',response)
        bars.extend(payload.get('bars',{}).get('BTC/USD',[]))
        if len(bars)>60000:raise ValueError('History exceeds 60,000 bars; shorten the interval or use a larger timeframe')
        next_token=payload.get('next_page_token')
        if not next_token: break
        if next_token==token: raise ValueError('Provider repeated pagination token')
        token=next_token
    else: raise ValueError('Dataset exceeds bounded pagination limit')
    rows=[]
    for i,b in enumerate(bars):
        at=advance(instant(b['t']),timeframe)
        if at>end_time: continue
        row={'symbol':'BTC/USD','at':at.isoformat(),'available_at':at.isoformat(),
             'open':b['o'],'high':b['h'],'low':b['l'],'close':b['c'],'volume':b['v']}
        if i+1<len(bars) and instant(bars[i+1]['t'])==at:
            price=bars[i+1]['o']
            row['quote']={'at':(at+timedelta(seconds=1)).isoformat(),'bid':price,'ask':price,'synthetic':True}
        rows.append(row)
    if not rows: raise ValueError('No accessible Bitcoin bars for this interval')
    return {'schema_version':1,'asset':'bitcoin','slippage_bps':5,'bars':rows,
            'manifest':{'provider':'Alpaca v1beta3','venue':'Alpaca US','fidelity':'bar_approximation','timeframe':timeframe,
                        'requested_start':start,'requested_end':end,'actual_start':rows[0]['at'],'actual_end':rows[-1]['at'],
                        'retrieved_at':datetime.now(timezone.utc).isoformat(),
                        'limitations':['Bars may contain quote midpoints; zero volume is not a trade',
                                      'Next-bar open is a synthetic execution proxy, not a historical bid/ask quote',
                                      'Bar marks cannot reproduce continuous risk execution']}}


def stock_dataset(db):
    universe=db.execute('SELECT MAX(id) FROM universe_snapshots').fetchone()[0]
    instruments=db.execute("SELECT i.id,i.symbol,c.sector FROM instruments i LEFT JOIN instrument_context c ON c.instrument_id=i.id WHERE i.id IN (SELECT instrument_id FROM universe_memberships WHERE snapshot_id=?) OR i.symbol='SPY' ORDER BY i.symbol",(universe,)).fetchall()
    sessions={s['trading_date']:s for s in db.execute('SELECT * FROM market_sessions ORDER BY trading_date')}
    rows,benchmark=[],[]
    for instrument in instruments:
        bars=db.execute("SELECT * FROM market_bars WHERE instrument_id=? AND timeframe='1Day' AND adjustment='raw' ORDER BY timestamp",(instrument['id'],)).fetchall()
        seen=set()
        selected=[]
        for bar in bars:
            day=bar['timestamp'][:10]
            if day in seen: raise ValueError('Multiple daily data providers/versions: select a canonical source before exporting')
            seen.add(day)
            if day in sessions: selected.append((bar,sessions[day]))
        for i,(bar,session) in enumerate(selected):
            at=instant(session['closes_at']).isoformat()
            if instrument['symbol']=='SPY':
                benchmark.append({'at':at,'close':bar['close']}); continue
            if not instrument['sector']: continue
            row={'symbol':instrument['symbol'],'sector':instrument['sector'],'at':at,'available_at':at,
                 **{k:bar[k] for k in ('open','high','low','close','volume')}}
            if i+1<len(selected):
                next_bar,next_session=selected[i+1]
                row['quote']={'at':(instant(next_session['opens_at'])+timedelta(minutes=15)).isoformat(),'bid':next_bar['open'],'ask':next_bar['open'],'synthetic':True}
                row['exit_quote']={'at':(instant(next_session['closes_at'])-timedelta(minutes=5)).isoformat(),'bid':next_bar['close'],'ask':next_bar['close'],'synthetic':True}
            rows.append(row)
    rows.sort(key=lambda r:(instant(r['at']),r['symbol']))
    if not rows: raise ValueError('Captured daily bars, sectors, and market calendar are required')
    return {'schema_version':1,'asset':'stocks','slippage_bps':5,'bars':rows,'benchmarks':{'SPY (price return)':benchmark},
            'manifest':{'provider':'captured daily stock bars','venue':'Alpaca stock data','fidelity':'daily_bar_approximation',
                        'point_in_time_membership':False,'universe_snapshot':universe,'actual_start':rows[0]['at'],'actual_end':rows[-1]['at'],
                        'limitations':['Current universe and sectors; survivorship bias',
                                      'Open and close prices do not reproduce 09:45 entries or near-close exits',
                                      'Raw prices: corporate action adjustment is required before performance interpretation']}}


def save_dataset(db, data, storage):
    path=Path(storage)/'importing.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(canonical(data))
    try: return register_dataset(db,path,storage)
    finally: path.unlink(missing_ok=True)
