"""Separate, revision-aware market store; bounded cursors keep research off the app DB."""
from pathlib import Path
from datetime import timedelta
import json
import sqlite3
from urllib.parse import urlencode
from .engine import canonical, instant
from .timeframes import TIMEFRAMES, boundary, advance


def connect_history(path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path); db.row_factory=sqlite3.Row
    db.executescript('''PRAGMA journal_mode=WAL; PRAGMA busy_timeout=3000;
    CREATE TABLE IF NOT EXISTS bars (
      timeframe TEXT NOT NULL, at TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL,
      PRIMARY KEY(timeframe,at,observed_at));
    CREATE INDEX IF NOT EXISTS bars_lookup ON bars(timeframe,at);
    CREATE TABLE IF NOT EXISTS quotes (
      at TEXT PRIMARY KEY, observed_at TEXT NOT NULL, bid REAL NOT NULL, ask REAL NOT NULL,
      bid_size REAL, ask_size REAL);
    CREATE TABLE IF NOT EXISTS collection_state (
      key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS metadata (at TEXT PRIMARY KEY,payload_json TEXT NOT NULL);
    ''')
    return db


def import_rows(db, timeframe, bars, observed_at, *, historical=False):
    if timeframe not in TIMEFRAMES: raise ValueError('Unsupported timeframe')
    with db:
        for row in bars:
            at=instant(row['at']).isoformat()
            available=instant(row.get('available_at',observed_at)).isoformat()
            if instant(available)<instant(at): raise ValueError('Availability precedes completed bar')
            if not historical and instant(available)>instant(observed_at): raise ValueError('Future availability')
            payload={**row,'at':at,'available_at':available,'historical_approximation':historical}
            for key in ('open','high','low','close'):
                from .engine import positive
                positive(payload[key],key)
            if not float(payload['low'])<=min(float(payload['open']),float(payload['close']))<=max(float(payload['open']),float(payload['close']))<=float(payload['high']):
                raise ValueError('Invalid OHLC range')
            previous=db.execute('SELECT payload_json FROM bars WHERE timeframe=? AND at=? ORDER BY observed_at DESC LIMIT 1',(timeframe,at)).fetchone()
            # Repeated observations do not manufacture revisions or invalidate caches.
            if previous:
                old=json.loads(previous[0])
                if all(old.get(k)==payload.get(k) for k in ('open','high','low','close','volume')): continue
            db.execute('INSERT OR IGNORE INTO bars VALUES (?,?,?,?)',(timeframe,at,observed_at,canonical(payload)))


def collect(db, broker, configs, now):
    quote=broker.quote(now)
    at=now.isoformat()
    meta=db.execute('SELECT at FROM metadata ORDER BY at DESC LIMIT 1').fetchone()
    if not meta or (now-instant(meta[0])).total_seconds()>=3600:
        payload=broker.metadata()
        with db: db.execute('INSERT INTO metadata VALUES (?,?)',(at,canonical(payload)))
    with db:
        db.execute('INSERT OR IGNORE INTO quotes VALUES (?,?,?,?,?,?)',
                   (instant(quote['t']).isoformat(),at,float(quote['bp']),float(quote['ap']),quote.get('bs'),quote.get('as')))
    for timeframe in sorted({c.timeframe for c in configs}):
        end=boundary(now,timeframe)
        # Give the provider a short publication interval after a completed bar.
        if (now-end).total_seconds()<5: continue
        state=db.execute('SELECT value FROM collection_state WHERE key=?',('latest:'+timeframe,)).fetchone()
        if state and state[0]==end.isoformat(): continue
        periods=max(max(c.slow,c.entry)+2 for c in configs if c.timeframe==timeframe)
        params={'symbols':'BTC/USD','timeframe':timeframe,'start':advance(end,timeframe,-periods).isoformat(),
                'end':end.isoformat(),'limit':10000,'sort':'asc'}
        result=broker.request('GET','/v1beta3/crypto/us/bars?'+urlencode(params),data=True)
        rows=[]
        for bar in result.get('bars',{}).get('BTC/USD',[]):
            close=advance(instant(bar['t']),timeframe)
            if close>end: continue
            rows.append({'symbol':'BTC/USD','at':close.isoformat(),'available_at':at,
                         'open':bar['o'],'high':bar['h'],'low':bar['l'],'close':bar['c'],'volume':bar['v']})
        if not rows or instant(rows[-1]['at'])!=end: raise ValueError(f'{timeframe}: latest completed bar unavailable')
        import_rows(db,timeframe,rows,at)
        with db: db.execute('INSERT INTO collection_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('latest:'+timeframe,end.isoformat()))
    return quote


def bars(db,timeframe,start,end,cutoff):
    """Latest revision known by cutoff; caller enforces decision-time availability."""
    cursor=db.execute('''SELECT b.* FROM bars b WHERE timeframe=? AND at>=? AND at<? AND observed_at<=?
      AND observed_at=(SELECT MAX(r.observed_at) FROM bars r WHERE r.timeframe=b.timeframe AND r.at=b.at AND r.observed_at<=?)
      ORDER BY at''',(timeframe,start,end,cutoff,cutoff))
    for row in cursor: yield json.loads(row['payload_json'])


def replay_bars(db,timeframe,start,end,cutoff):
    # First observation only: later corrections must never rewrite the past.
    for row in db.execute('''SELECT b.* FROM bars b WHERE timeframe=? AND at>=? AND at<? AND observed_at<=?
      AND observed_at=(SELECT MIN(r.observed_at) FROM bars r WHERE r.timeframe=b.timeframe AND r.at=b.at)
      ORDER BY CASE WHEN json_extract(payload_json,'$.historical_approximation')=1 THEN at
                    ELSE json_extract(payload_json,'$.available_at') END,at''',(timeframe,start,end,cutoff)):
        yield json.loads(row['payload_json'])


def bar_revisions(db,timeframe,start,end,cutoff):
    """Publish corrections when observed, without rewriting earlier decisions."""
    for row in db.execute('''SELECT payload_json FROM bars WHERE timeframe=? AND at>=? AND at<? AND observed_at<=?
      ORDER BY CASE WHEN json_extract(payload_json,'$.historical_approximation')=1 THEN at
                    ELSE json_extract(payload_json,'$.available_at') END,at''',(timeframe,start,end,cutoff)):
        yield json.loads(row[0])


def quotes(db,start,end,cutoff):
    for row in db.execute('SELECT * FROM quotes WHERE at>=? AND at<? AND observed_at<=? ORDER BY observed_at,at',(start,end,cutoff)):
        yield dict(row)


def latest_bars(db,config,now):
    end=boundary(now,config.timeframe)
    rows=list(bars(db,config.timeframe,advance(end,config.timeframe,-max(config.slow,config.entry)-2).isoformat(),
                   (end+timedelta(microseconds=1)).isoformat(),now.isoformat()))
    if not rows or instant(rows[-1]['at'])!=end: raise ValueError('Completed decision bar is stale')
    for before,after in zip(rows,rows[1:]):
        if advance(instant(before['at']),config.timeframe)!=instant(after['at']): raise ValueError('Decision history has gaps')
    return rows
