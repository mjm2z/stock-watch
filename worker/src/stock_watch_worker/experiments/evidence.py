"""Asset/feed aware, receipt-time evidence; historical warmup is never a live bar."""
from datetime import timedelta
from pathlib import Path
import sqlite3
from .model import canonical, digest, instant, stamp, money

SCHEMA = '''
CREATE TABLE IF NOT EXISTS feed_events (
 id INTEGER PRIMARY KEY, asset TEXT NOT NULL, feed TEXT NOT NULL, symbol TEXT NOT NULL,
 kind TEXT NOT NULL, at TEXT NOT NULL, observed TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(asset,feed,symbol,kind,at,observed,payload));
CREATE INDEX IF NOT EXISTS feed_events_time ON feed_events(asset,feed,symbol,kind,at,observed);
CREATE TABLE IF NOT EXISTS bars (
 id INTEGER PRIMARY KEY, asset TEXT NOT NULL, feed TEXT NOT NULL, symbol TEXT NOT NULL,
 at TEXT NOT NULL, observed TEXT NOT NULL, provenance TEXT NOT NULL, payload TEXT NOT NULL,
 hash TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'alpaca', timeframe TEXT NOT NULL DEFAULT '5Min',
 UNIQUE(provider,asset,feed,symbol,timeframe,at,hash,provenance));
CREATE INDEX IF NOT EXISTS bars_lookup ON bars(asset,feed,symbol,timeframe,at,observed);
CREATE TABLE IF NOT EXISTS pins (decision_id TEXT NOT NULL,bar_id INTEGER NOT NULL REFERENCES bars(id),PRIMARY KEY(decision_id,bar_id));
CREATE TABLE IF NOT EXISTS news (
 id TEXT NOT NULL, revision TEXT NOT NULL, symbol TEXT NOT NULL, published TEXT NOT NULL,
 observed TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(id,revision,symbol));
CREATE INDEX IF NOT EXISTS news_time ON news(symbol,published,observed);
CREATE TABLE IF NOT EXISTS health (component TEXT PRIMARY KEY,at TEXT NOT NULL,error TEXT);
CREATE TABLE IF NOT EXISTS health_events (component TEXT NOT NULL,at TEXT NOT NULL,error TEXT,PRIMARY KEY(component,at));
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY,value TEXT NOT NULL);
'''

def connect(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=3000')
    db.executescript(SCHEMA)
    return db

def put_bar(db,asset,feed,symbol,at,observed,bar,provenance):
    if provenance not in ('stream','historical'): raise ValueError('Unknown provenance')
    prices=[money(bar[k]) for k in ('open','high','low','close')]
    if min(prices)<=0 or prices[1]<max(prices) or prices[2]>min(prices) or money(bar['volume'])<0:
        raise ValueError('Invalid OHLCV')
    payload=canonical(bar)
    with db:
        db.execute('INSERT OR IGNORE INTO bars(asset,feed,symbol,at,observed,provenance,payload,hash) VALUES (?,?,?,?,?,?,?,?)',
            (asset,feed,symbol,stamp(instant(at)),stamp(instant(observed)),provenance,payload,digest(bar)))

def aggregate(db,asset,feed,symbol,close,cutoff):
    """Five real minute bars, including corrections observed by the frozen cutoff."""
    import json
    rows=db.execute('''SELECT * FROM feed_events WHERE asset=? AND feed=? AND symbol=?
        AND kind IN ('b','u') AND at>=? AND at<? AND observed<=? ORDER BY at,observed,id''',
        (asset,feed,symbol,stamp(close-timedelta(minutes=5)),stamp(close),stamp(cutoff))).fetchall()
    minutes={r['at']:json.loads(r['payload']) for r in rows}
    expected=[stamp(close-timedelta(minutes=n)) for n in range(5,0,-1)]
    if any(t not in minutes for t in expected): return False
    bars=[minutes[t] for t in expected]
    bar=dict(open=bars[0]['o'],high=max(float(r['h']) for r in bars),low=min(float(r['l']) for r in bars),close=bars[-1]['c'],volume=sum(float(r['v']) for r in bars))
    receipt=max(r['observed'] for r in rows)
    put_bar(db,asset,feed,symbol,stamp(close),receipt,bar,'stream')
    return True

def history(db,cfg,symbol,close,cutoff,calendar=None):
    import json
    aggregate(db,cfg['asset'],cfg['feed'],symbol,close,cutoff)
    rows=db.execute('''SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY at ORDER BY observed DESC,id DESC) n
        FROM bars WHERE asset=? AND feed=? AND symbol=? AND timeframe=? AND at<=? AND observed<=?)
        WHERE n=1 ORDER BY at DESC LIMIT 1000''',
        (cfg['asset'],cfg['feed'],symbol,cfg['timeframe'],stamp(close),stamp(cutoff))).fetchall()[::-1]
    if cfg['asset']=='stocks' and calendar:
        ranges=[(instant(c['opens']),instant(c['closes'])) for c in calendar]
        rows=[r for r in rows if any(a<instant(r['at'])<=b for a,b in ranges)]
    rows=rows[-251:]
    if len(rows)<251: raise ValueError('collecting: need 251 completed bars')
    if rows[-1]['at']!=stamp(close) or rows[-1]['provenance']!='stream':
        raise ValueError('missing completed stream bar at decision cutoff')
    # Missing crypto intervals are always a gap. Equity overnight/session closures
    # are valid, but an intraday gap never silently becomes a synthetic bar.
    from .model import NY
    for before,after in zip(rows,rows[1:]):
        a,b=instant(before['at']),instant(after['at'])
        if b-a!=timedelta(minutes=5) and (cfg['asset']=='bitcoin' or a.astimezone(NY).date()==b.astimezone(NY).date()):
            raise ValueError('missing intraday bars')
        if cfg['asset']=='stocks' and calendar and b-a!=timedelta(minutes=5):
            if any(a<t<=b and stamp(t) not in (before['at'],after['at']) for opened,closed in ranges for t in (opened+timedelta(minutes=5),closed)):
                raise ValueError('missing session boundary bars')
    return [{**json.loads(r['payload']),'at':r['at'],'evidence_id':r['id'],'provenance':r['provenance']} for r in rows]

def pin(db,decision,rows):
    with db:
        db.executemany('INSERT OR IGNORE INTO pins VALUES (?,?)',[(decision,r['evidence_id']) for r in rows])

def fresh_news(db,symbol,cutoff):
    since=stamp(cutoff-timedelta(minutes=60)); until=stamp(cutoff)
    return [dict(r) for r in db.execute('''SELECT id,revision,published,first_observed observed FROM
        (SELECT *,MIN(observed) OVER(PARTITION BY id,symbol) first_observed,
        ROW_NUMBER() OVER(PARTITION BY id,symbol ORDER BY observed DESC) n FROM news WHERE symbol=? AND observed<=?)
        WHERE n=1 AND published BETWEEN ? AND ? AND first_observed BETWEEN ? AND ? ORDER BY published LIMIT 100''',
        (symbol,until,since,until,since,until))]

def quote(db,cfg,symbol,now):
    import json
    row=db.execute("SELECT * FROM feed_events WHERE asset=? AND feed=? AND symbol=? AND kind='q' AND observed<=? AND at<=? ORDER BY at DESC,id DESC LIMIT 1",(cfg['asset'],cfg['feed'],symbol,stamp(now),stamp(now))).fetchone()
    if not row or not 0<=(now-instant(row['observed'])).total_seconds()<=5 or not 0<=(now-instant(row['at'])).total_seconds()<=5:
        raise ValueError('quote is older than five seconds')
    q=json.loads(row['payload'])
    if money(q['bp'])<=0 or money(q['ap'])<money(q['bp']): raise ValueError('quote is invalid or crossed')
    return q

def prune(db,now):
    with db:
        db.execute('DELETE FROM feed_events WHERE observed<?',(stamp(now-timedelta(days=7)),))
        db.execute('DELETE FROM bars WHERE observed<? AND id NOT IN (SELECT bar_id FROM pins)',(stamp(now-timedelta(days=90)),))

def record_health(db,component,now,error=None):
    with db:
        db.execute('INSERT OR REPLACE INTO health VALUES (?,?,?)',(component,stamp(now),error))
        db.execute('INSERT OR REPLACE INTO health_events VALUES (?,?,?)',(component,stamp(now),error))
