"""Primary-source research context. These documents never authorize orders."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from .model import UNIVERSE, digest, instant, stamp
from .store import health

FEEDS={'Federal Reserve':'https://www.federalreserve.gov/feeds/press_all.xml',
    'BLS employment':'https://www.bls.gov/feed/empsit.rss',
    'BLS inflation':'https://www.bls.gov/feed/cpi.rss'}

def parse(raw,source,observed):
    if len(raw)>1048576 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper(): raise ValueError('Unsupported research XML')
    root=ElementTree.fromstring(raw); result=[]
    for node in list(root.iter()):
        if node.tag.split('}')[-1] not in ('item','entry'): continue
        fields={child.tag.split('}')[-1]:(child.text or child.attrib.get('href','')).strip() for child in node}
        url=fields.get('link',''); host=urlsplit(url).hostname or ''
        if urlsplit(url).scheme!='https' or host not in ('www.bls.gov','www.federalreserve.gov','bls.gov','federalreserve.gov'): continue
        when=fields.get('pubDate') or fields.get('published') or fields.get('updated')
        if not when: continue
        try: published=stamp(instant(when))
        except ValueError: published=stamp(parsedate_to_datetime(when))
        title=' '.join(fields.get('title','').split())[:300]
        result.append((digest({'source':source,'url':url,'published':published,'title':title}),source,None,title,url,published,stamp(observed)))
        if len(result)>=50: break
    return result

def collect(db,now):
    for name,url in FEEDS.items():
        component='context:'+name
        last=db.execute('SELECT at FROM experiment_health WHERE component=?',(component,)).fetchone()
        if last and now-instant(last[0])<timedelta(hours=1): continue
        try:
            request=Request(url,headers={'User-Agent':'StockWatch research context/1.0','Accept':'application/rss+xml, application/atom+xml, text/xml'})
            with urlopen(request,timeout=10) as response: raw=response.read(1048577)
            rows=parse(raw,name,datetime.now(timezone.utc))
            with db: db.executemany('INSERT OR IGNORE INTO experiment_context VALUES (?,?,?,?,?,?,?)',rows)
            health(db,component,now,detail={'articles':len(rows)})
        except Exception as error: health(db,component,now,error)
    # Reuse cached SEC accession provenance; avoid a second EDGAR collector.
    # Finish the read before writing. An open cursor retains a WAL snapshot;
    # another writer's commit makes upgrading it fail with SQLITE_BUSY_SNAPSHOT,
    # which cannot be resolved by the connection's busy timeout.
    cached=db.execute("SELECT symbol,payload_json FROM company_context WHERE status='ready' AND payload_json IS NOT NULL").fetchall()
    for row in cached:
        if row['symbol'] not in UNIVERSE: continue
        document=json.loads(row['payload_json'])
        with db:
            for filing in document.get('filings',[])[:20]:
                if not filing.get('accepted'): continue
                item=(digest({'symbol':row['symbol'],'accession':filing['accession']}),'SEC EDGAR',row['symbol'],filing['form']+' · '+str(filing.get('description',''))[:200],filing['url'],stamp(instant(filing['accepted'])),stamp(instant(document['observedAt'])))
                db.execute('INSERT OR IGNORE INTO experiment_context VALUES (?,?,?,?,?,?,?)',item)
