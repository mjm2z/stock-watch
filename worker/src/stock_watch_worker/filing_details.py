"""Bounded, plain-text SEC filing projections. No trading authority."""
import json
import math
import re
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

MAX_DOCUMENT = 20 * 1024 * 1024

def document_url(cik, accession, name):
    if not str(cik).isdigit() or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
        raise ValueError('Invalid SEC filing identity')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:htm|html|txt)', name, re.I) or '..' in name:
        raise ValueError('Document format is unsupported; view the original filing.')
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{name}'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('SEC document redirected; view the original filing.')

def download(sec, url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'www.sec.gov' or not parsed.path.startswith('/Archives/edgar/data/'):
        raise ValueError('Invalid SEC document URL')
    sec._limiter.wait()
    request = Request(url, headers={'User-Agent': sec._user_agent, 'Accept-Encoding': 'identity'})
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        if response.headers.get('Content-Encoding', 'identity') != 'identity':
            raise ValueError('Unsupported document encoding; view the original filing.')
        data = response.read(MAX_DOCUMENT + 1)
        if len(data) > MAX_DOCUMENT:
            raise ValueError('Document exceeds the 20 MiB extraction limit; view the original filing.')
        if data.startswith(b'%PDF'):
            raise ValueError('PDF extraction is unsupported; view the original filing.')
        return data.decode('utf-8', errors='replace')

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = bool(self.stack and self.stack[-1][1]) or tag in ('script','style','noscript','iframe','object','svg','ix:hidden','ix:header') or 'hidden' in attrs or attrs.get('aria-hidden') == 'true' or bool(re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', attrs.get('style',''), re.I))
        if tag not in ('br','hr','img','meta','link','input','wbr','area','base','embed','source','track','col','param'):
            self.stack.append((tag, hidden))
        if not hidden and tag in ('p','div','br','tr','h1','h2','h3','h4','li'):
            self.parts.append('\n')
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.parts.append(data)

def extract(document):
    parser = TextParser()
    parser.feed(document)
    text = '\n'.join(' '.join(line.split()) for line in ''.join(parser.parts).splitlines() if line.strip())
    # Recognized Item headings retain source wording; no generated summaries.
    sections = []
    headings = list(re.finditer(r'(?im)^item\s+\d+[a-z]?\.?[ \t]+[^\n]{3,160}$', text))
    for i, heading in enumerate(headings[:12]):
        end = headings[i+1].start() if i+1 < len(headings) else len(text)
        body = text[heading.end():end].strip()
        if len(body) > 100:
            sections.append({'title': heading.group(), 'text': body.encode('utf-8')[:8000].decode('utf-8',errors='ignore')})
    excerpt = text.encode('utf-8')[:40000].decode('utf-8', errors='ignore')
    return {'text': excerpt, 'label': 'Opening source excerpt (may include the table of contents)', 'truncated': len(excerpt) < len(text), 'sections': sections}

class ExhibitIndex(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.links = [], None, []
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row, self.links = [], []
        if tag == 'a' and self.row is not None: self.links.append(dict(attrs).get('href',''))
    def handle_data(self, data):
        if self.row is not None: self.row.append(data)
    def handle_endtag(self, tag):
        if tag == 'tr' and self.row is not None:
            text = ' '.join(self.row)
            if re.search(r'EX-99(?:\.\d+)?', text, re.I) and re.search(r'earnings|financial results|results of operations', text, re.I):
                self.rows.extend(self.links)
            self.row = None

def earnings_exhibit(sec, issuer, filing):
    index = ExhibitIndex()
    index.feed(download(sec,filing['url']))
    prefix = f"/Archives/edgar/data/{int(issuer['cik'])}/{filing['accession'].replace('-', '')}/"
    candidates = set()
    for href in index.rows:
        if href.startswith(prefix) and '/' not in href[len(prefix):]:
            candidates.add(href[len(prefix):])
    if len(candidates) != 1:
        return None
    url = document_url(issuer['cik'],filing['accession'],candidates.pop())
    return {'source':url,'excerpt':extract(download(sec,url))}

def exact_facts(facts, accession):
    from .company_context import METRICS
    result = []
    for label, concepts, unit, _ in METRICS:
        for concept in concepts:
            rows = facts.get('facts',{}).get('us-gaap',{}).get(concept,{}).get('units',{}).get(unit,[])
            matches = [r for r in rows if r.get('accn') == accession and isinstance(r.get('val'),(int,float)) and not isinstance(r['val'],bool) and math.isfinite(r['val'])]
            if matches:
                seen = set()
                for row in matches:
                    key = (row.get('start'),row.get('end'),row['val'])
                    if key in seen: continue
                    seen.add(key)
                    result.append({'label':label,'concept':concept,'unit':unit,'value':row['val'],'start':row.get('start'),'end':row.get('end')})
                break
    return result[:100]

def run_next(db, sec, now):
    from .company_context import stamp, project
    with db:
        db.execute("UPDATE filing_details SET status='unavailable',error='Collection interrupted; retry after cooldown.',retry_after=? WHERE status='running'", (stamp(now+timedelta(minutes=15)),))
        db.execute("DELETE FROM filing_details WHERE status NOT IN ('queued','running') AND requested_at<?", (stamp(now-timedelta(days=30)),))
    row = db.execute("SELECT * FROM filing_details WHERE status='queued' ORDER BY requested_at LIMIT 1").fetchone()
    if not row: return False
    key = (row['symbol'],row['accession'])
    with db: db.execute("UPDATE filing_details SET status='running' WHERE symbol=? AND accession=?",key)
    try:
        issuer = json.loads(db.execute('SELECT payload_json FROM company_context WHERE symbol=?',(row['symbol'],)).fetchone()[0])
        filing = next((f for f in issuer['filings'] if f['accession']==row['accession']),None)
        if not filing: raise ValueError('Filing is no longer in the retained issuer list.')
        if not filing.get('primaryDocument'):
            refreshed = project(sec.get_submissions(issuer['cik']),{},issuer['cik'],row['symbol'],issuer['kind'],now)
            filing = next((f for f in refreshed['filings'] if f['accession']==row['accession']),None)
        if not filing: raise ValueError('Document metadata unavailable; view the original filing.')
        url = document_url(issuer['cik'],row['accession'],filing.get('primaryDocument',''))
        excerpt = extract(download(sec,url))
        metrics, note, exhibit = [], None, None
        if filing.get('earningsRelated'):
            try: exhibit = earnings_exhibit(sec,issuer,filing)
            except Exception: pass
        if issuer['kind'] != 'fund':
            try: metrics = exact_facts(sec.get_company_facts(issuer['cik']),row['accession'])
            except Exception: note = 'Exact-accession financial facts could not be refreshed.'
        payload = json.dumps({'filing':filing,'source':url,'excerpt':excerpt,'exhibit':exhibit,'metrics':metrics,'note':note,'observedAt':stamp(now)},ensure_ascii=False,allow_nan=False)
        if len(payload.encode()) > 524288: raise ValueError('Extracted result exceeds storage limit.')
        with db:
            # Evict oldest completed projections before insertion; never pending work.
            while db.execute('SELECT coalesce(sum(length(CAST(payload_json AS BLOB))),0) FROM filing_details').fetchone()[0] + len(payload.encode()) > 64*1024*1024:
                db.execute("DELETE FROM filing_details WHERE rowid IN (SELECT rowid FROM filing_details WHERE status NOT IN ('queued','running') ORDER BY requested_at LIMIT 1)")
            db.execute("UPDATE filing_details SET status='ready',payload_json=?,updated_at=?,retry_after=?,error=NULL WHERE symbol=? AND accession=?",(payload,stamp(now),stamp(now+timedelta(days=30)),*key))
    except Exception as error:
        message = str(error) if isinstance(error,ValueError) else 'SEC document unavailable; retry after cooldown.'
        with db: db.execute("UPDATE filing_details SET status='unavailable',error=?,retry_after=? WHERE symbol=? AND accession=?",(message[:300],stamp(now+timedelta(minutes=15)),*key))
    return True
