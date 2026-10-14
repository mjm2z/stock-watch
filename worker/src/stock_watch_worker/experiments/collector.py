"""Bounded REST warmup/news/calendar, independent of account execution."""
from datetime import datetime, timedelta, timezone
import json
import os
import time
from urllib.parse import urlencode
from ..database import connect
from . import evidence
from .broker import Broker
from .model import NY, UNIVERSE, boundary, canonical, config, digest, instant, stamp
from .store import health

def warmup(market,broker,asset,now):
    cfg=config(asset,'trend'); symbols=cfg['universe']
    base='/v2/stocks/bars' if asset=='stocks' else '/v1beta3/crypto/us/bars'
    query={'symbols':','.join(symbols),'timeframe':'5Min','start':stamp(now-timedelta(days=10 if asset=='stocks' else 2)),
        'end':stamp(now-timedelta(minutes=16)),'limit':10000,'sort':'asc'}
    if asset=='stocks': query.update(feed='iex',adjustment='raw')
    count=0; seen=set()
    for _ in range(10):
        result=broker.request('GET',base+'?'+urlencode(query),data=True)
        for symbol,rows in result.get('bars',{}).items():
            if symbol not in symbols: continue
            for row in rows:
                at=instant(row['t'])+timedelta(minutes=5)
                if asset=='stocks':
                    local=at.astimezone(NY)
                    # Session-specific early closes are checked below at decision
                    # time; pre/post-market bars cannot seed regular-session rules.
                    if not (9*60+35 <= local.hour*60+local.minute <=16*60): continue
                evidence.put_bar(market,asset,cfg['feed'],symbol,stamp(at),stamp(datetime.now(timezone.utc)),
                    dict(zip(('open','high','low','close','volume'),(row[k] for k in ('o','h','l','c','v')))),'historical')
                count+=1
        token=result.get('next_page_token')
        if not token: return count
        if token in seen: raise ValueError('Warmup pagination repeated')
        seen.add(token); query['page_token']=token
    raise ValueError('Warmup pagination limit exceeded')

def calendar(db,broker,now):
    from ..market_calendar import MarketSession
    start=(now-timedelta(days=10)).date().isoformat(); end=(now+timedelta(days=40)).date().isoformat()
    rows=broker.calendar(start,end)
    settlement_days=[]; error=None
    if any(not row.get('settlement_date') for row in rows):
        try:
            from datetime import date
            settlement_days=sorted({date.fromisoformat(row['date']) for row in broker.calendar(start,end,'SETTLEMENT')})
        except Exception as problem: error='Settlement dates unavailable: '+str(problem)[:200]
    with db:
        for row in rows:
            session=MarketSession.from_alpaca(row)
            settlement=row.get('settlement_date')
            if not settlement:
                next_date=next((day for day in settlement_days if day>session.trading_date),None)
                settlement=next_date.isoformat() if next_date else None
            if settlement:
                from datetime import date
                parsed=date.fromisoformat(settlement)
                if parsed<=session.trading_date: raise ValueError('Invalid broker settlement date')
            db.execute('INSERT OR REPLACE INTO experiment_calendar VALUES (?,?,?,?,?)',
                (session.trading_date.isoformat(),stamp(session.opens_at),stamp(session.closes_at),settlement,stamp(now)))
    health(db,'settlement-calendar',now,error,{'source':'Alpaca settlement_date or explicit SETTLEMENT calendar; never the trading calendar'})

def news(market,broker,now):
    previous=market.execute("SELECT value FROM state WHERE key='news_cursor'").fetchone()
    start=max(instant(previous[0])-timedelta(minutes=5),now-timedelta(hours=2)) if previous else now-timedelta(hours=1)
    query={'start':stamp(start),'end':stamp(now),'limit':50,'sort':'asc','include_content':'false'}
    seen=set()
    for _ in range(5):
        result=broker.request('GET','/v1beta1/news?'+urlencode(query),data=True)
        for article in result.get('news',[]):
            published=stamp(instant(article['created_at'])); revision=digest(article)
            links=set(article.get('symbols',[]))
            if links & {'BTC','BTCUSD','BTC/USD'}: links.add('BTC/USD')
            with market:
                for symbol in links & (set(UNIVERSE)|{'BTC/USD'}):
                    market.execute('INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?)',
                        (str(article['id']),revision,symbol,published,stamp(datetime.now(timezone.utc)),canonical(article)))
        token=result.get('next_page_token')
        if not token:
            with market: market.execute("INSERT OR REPLACE INTO state VALUES ('news_cursor',?)",(stamp(now),))
            return
        if token in seen: raise ValueError('News pagination repeated')
        seen.add(token); query['page_token']=token
    raise ValueError('News pagination incomplete; news entries blocked')

def collect(db,market,now):
    for asset in ('stocks','bitcoin'):
        try:
            broker=Broker(asset)
            marker=market.execute('SELECT value FROM state WHERE key=?',('warmup:'+asset,)).fetchone()
            if not marker or now-instant(marker[0])>timedelta(minutes=15):
                warmup(market,broker,asset,now)
                with market: market.execute('INSERT OR REPLACE INTO state VALUES (?,?)',('warmup:'+asset,stamp(now)))
            if asset=='stocks': calendar(db,broker,now)
            cfg=config(asset,'trend'); close=boundary(now-timedelta(seconds=35))
            for symbol in cfg['universe']:
                # Warmup's last 16-minute restriction is bridged by observed
                # stream bars, never by mislabeling historical responses.
                for age in range(4):
                    at=close-timedelta(minutes=5*age)
                    evidence.aggregate(market,asset,cfg['feed'],symbol,at,at+timedelta(seconds=35))
            stream=market.execute('SELECT * FROM health WHERE component=?',('stream:'+asset,)).fetchone()
            today=db.execute('SELECT * FROM experiment_calendar WHERE date=?',(now.astimezone(NY).date().isoformat(),)).fetchone()
            closed=asset=='stocks' and (not today or not instant(today['opens'])<=now<instant(today['closes']))
            stream_error=None if closed else stream['error'] if stream else 'No stream subscription evidence'
            if not closed and stream and now-instant(stream['at'])>timedelta(seconds=120): stream_error='Stream observations are stale'
            health(db,'stream:'+asset,now,stream_error,{'feed':cfg['feed'],'market_closed':closed,'last_observed':stream['at'] if stream else None})
            health(db,'collection:'+asset,now)
        except Exception as error: health(db,'collection:'+asset,now,error)
    try:
        news(market,Broker('stocks'),now)
        evidence.record_health(market,'news',datetime.now(timezone.utc))
        health(db,'news',now)
    except Exception as error:
        evidence.record_health(market,'news',datetime.now(timezone.utc),str(error)[:300])
        health(db,'news',now,error)
    evidence.prune(market,now)
    from .research import propose
    propose(db,now)
    from .context import collect as collect_context
    collect_context(db,now)
    import shutil
    path=db.execute('PRAGMA database_list').fetchone()[2]
    health(db,'storage',now,detail={'evidence_bytes':os.path.getsize(path+'.experiment-evidence.db'),
        'available_bytes':shutil.disk_usage(os.path.dirname(path)).free})

def main():
    path=os.environ['STOCK_WATCH_DATABASE_PATH']; db=connect(path); market=evidence.connect(path+'.experiment-evidence.db')
    try:
        while True:
            collect(db,market,datetime.now(timezone.utc))
            time.sleep(60)
    finally: db.close(); market.close()

if __name__=='__main__': main()
