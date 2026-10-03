"""Bounded SEC display context. Never creates instruments, signals or orders."""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .database import connect
from .providers.sec import SecClient, MinimumIntervalLimiter

FORMS = {'10-K', '10-Q', '8-K', '20-F', '40-F', '6-K', 'DEF 14A',
         'N-CSR', 'N-CSRS', 'N-PORT', 'NPORT-P', 'N-CEN', '497', '497K',
         '485APOS', '485BPOS', '424B2', '424B3', '424B4', '424B5'}
METRICS = [
    ('Revenue', ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'), 'USD', True),
    ('Net income', ('NetIncomeLoss', 'ProfitLoss'), 'USD', True),
    ('Diluted EPS', ('EarningsPerShareDiluted',), 'USD/shares', True),
    ('Operating cash flow', ('NetCashProvidedByUsedInOperatingActivities',), 'USD', True),
    ('Cash and equivalents', ('CashAndCashEquivalentsAtCarryingValue',), 'USD', False),
]


def stamp(now):
    return now.astimezone(timezone.utc).isoformat()


def filing_url(cik, accession):
    if not str(cik).isdigit() or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', str(accession)):
        return None
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{accession}-index.html'


def project(submissions, facts, cik, symbol, kind, now, facts_at=None):
    """Keep accession-level provenance; no inferred quarters, growth or forecasts."""
    recent = submissions.get('filings', {}).get('recent', {})
    rows = []
    accepted = {}
    for i, accession in enumerate(recent.get('accessionNumber', [])[:2000]):
        def value(key):
            values = recent.get(key, [])
            return values[i] if i < len(values) else ''
        form = str(value('form'))
        url = filing_url(cik, accession)
        if not url:
            continue
        accepted[accession] = str(value('acceptanceDateTime')) or None
        if form.removesuffix('/A') not in FORMS:
            continue
        rows.append({'accession': accession, 'form': form, 'filed': value('filingDate'),
                     'accepted': accepted[accession], 'period': value('reportDate'),
                     'description': str(value('primaryDocDescription'))[:200], 'url': url,
                     'primaryDocument': str(value('primaryDocument')), 'items': str(value('items')),
                     'earningsRelated': form.removesuffix('/A') == '8-K' and
                     '2.02' in re.split(r'[,;\s]+', str(value('items')))})
    rows.sort(key=lambda r: (r['filed'], r['accession']), reverse=True)
    # Registered funds and investment companies must not receive corporate ratios.
    if str(submissions.get('sic', '')) in ('6722', '6726') or any(
        str(f).startswith(('N-', 'NPORT', '485')) for f in recent.get('form', [])
    ):
        kind = 'fund'
    if str(int(cik)) == '884394':
        kind = 'fund'  # SPDR S&P 500 ETF Trust (SEC CIK); may lack fund-directory series.
    metrics = []
    if kind != 'fund':
        for label, concepts, unit, duration in METRICS:
            candidates = []
            for priority, concept in enumerate(concepts):
                for entry in facts.get('facts', {}).get('us-gaap', {}).get(concept, {}).get('units', {}).get(unit, []):
                    try:
                        end = date.fromisoformat(entry['end'])
                        filed = date.fromisoformat(entry['filed'])
                        val = entry['val']
                        url = filing_url(cik, entry.get('accn'))
                        if (not isinstance(val, (float, int)) or isinstance(val, bool) or not math.isfinite(val)
                                or not url or filed > now.date() or end > filed):
                            continue
                        # Annual reports only for duration metrics; never label YTD as a quarter.
                        if duration and (entry.get('form') not in ('10-K', '10-K/A') or
                                         not 330 <= (end - date.fromisoformat(entry['start'])).days <= 400):
                            continue
                        if not duration and entry.get('form') not in ('10-K', '10-K/A', '10-Q', '10-Q/A'):
                            continue
                        candidates.append((end, filed, -priority, entry, concept))
                    except (KeyError, ValueError, TypeError):
                        continue
            if candidates:
                _, _, _, entry, concept = max(candidates, key=lambda x: x[:3])
                metrics.append({'label': label, 'value': entry['val'], 'unit': unit,
                                'start': entry.get('start') if duration else None, 'end': entry['end'],
                                'periodLabel': 'Annual' if duration else 'As of', 'filed': entry['filed'],
                                'accession': entry['accn'], 'accepted': accepted.get(entry['accn']),
                                'concept': concept, 'url': filing_url(cik, entry['accn'])})
            else:
                metrics.append({'label': label, 'value': None, 'unit': unit, 'periodLabel': 'Unavailable'})
    return {'symbol': symbol, 'name': str(submissions.get('name') or symbol)[:200],
            'cik': str(cik).zfill(10), 'kind': kind, 'filings': rows[:20], 'metrics': metrics,
            'observedAt': stamp(now), 'factsObservedAt': facts_at,
            'source': 'SEC EDGAR', 'financialsNote': None}


def directory(db, sec, source, now):
    old = db.execute('SELECT * FROM company_context_directory WHERE source=?', (source,)).fetchone()
    if old and datetime.fromisoformat(old['updated_at']) > now - timedelta(days=1):
        return json.loads(old['payload_json'])
    if source == 'companies':
        raw = sec.get_company_tickers()
        mapping = {str(r['ticker']).upper(): str(r['cik_str']) for r in raw.values()
                   if isinstance(r, dict) and r.get('ticker') and str(r.get('cik_str', '')).isdigit()}
    else:
        raw = sec.get_fund_tickers()
        fields = raw.get('fields', [])
        mapping = {}
        for values in raw.get('data', []):
            row = dict(zip(fields, values))
            if row.get('symbol') and str(row.get('cik', '')).isdigit():
                mapping[str(row['symbol']).upper()] = str(row['cik'])
    if not mapping or len(mapping) > 100000:
        raise ValueError('SEC ticker directory is unavailable')
    with db:
        db.execute('INSERT OR REPLACE INTO company_context_directory VALUES (?,?,?)',
                   (source, stamp(now), json.dumps(mapping)))
    return mapping


def collect(db, sec, symbol, now):
    known = db.execute('SELECT id,cik FROM instruments WHERE symbol=?', (symbol,)).fetchone()
    kind = 'company'
    cik = str(known['cik']) if known and known['cik'] else None
    if not cik:
        companies = directory(db, sec, 'companies', now)
        cik = companies.get(symbol) or companies.get(symbol.replace('.', '-'))
    if not cik and symbol == 'SPY':
        # SEC filing index: /Archives/edgar/data/884394/0001193125-17-146441-index.htm
        cik, kind = '884394', 'fund'
    if not cik:
        funds = directory(db, sec, 'funds', now)
        cik = funds.get(symbol)
        kind = 'fund'
    if not cik:
        raise ValueError('No SEC issuer mapping found for this ticker. Fund and foreign-security coverage varies.')
    submissions = sec.get_submissions(cik)
    facts, facts_at, note = {}, None, None
    # Classify before asking for CompanyFacts; fund filings are still useful.
    preview = project(submissions, {}, cik, symbol, kind, now)
    if preview['kind'] != 'fund':
        try:
            cached = db.execute('SELECT facts_json,captured_at FROM company_fact_documents WHERE instrument_id=? ORDER BY captured_at DESC LIMIT 1', (known['id'],)).fetchone() if known else None
            if cached and datetime.fromisoformat(cached['captured_at'].replace('Z', '+00:00')) > now - timedelta(days=1):
                facts, facts_at = json.loads(cached['facts_json']), cached['captured_at']
            else:
                facts, facts_at = sec.get_company_facts(cik), stamp(now)
        except Exception:
            note = 'Reported financials could not be refreshed. Filings remain available.'
    result = project(submissions, facts, cik, symbol, preview['kind'], now, facts_at)
    result['financialsNote'] = note
    return result


def run_next(db, sec, now):
    # Caller holds an exclusive process lock; recover only this display queue.
    with db:
        db.execute("UPDATE company_context SET status='unavailable',error='SEC collection interrupted; check again after the cooldown.',retry_after=? WHERE status='running'", (stamp(now + timedelta(minutes=15)),))
    job = db.execute("SELECT symbol FROM company_context WHERE status='queued' ORDER BY requested_at LIMIT 1").fetchone()
    if not job:
        return False
    symbol = job['symbol']
    with db:
        db.execute("UPDATE company_context SET status='running' WHERE symbol=?", (symbol,))
    try:
        payload = collect(db, sec, symbol, now)
        with db:
            db.execute("UPDATE company_context SET status='ready',payload_json=?,updated_at=?,retry_after=?,error=NULL WHERE symbol=?",
                       (json.dumps(payload, allow_nan=False), stamp(now), stamp(now + timedelta(hours=6)), symbol))
    except Exception as error:
        # Never expose request headers, environment values or provider response bodies.
        message = str(error) if isinstance(error, ValueError) else 'SEC collection unavailable; retry after the cooldown.'
        with db:
            db.execute("UPDATE company_context SET status='unavailable',retry_after=?,error=? WHERE symbol=?",
                       (stamp(now + timedelta(minutes=15)), message[:300], symbol))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    args = parser.parse_args()
    with Path(args.database + '.company-context.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with connect(args.database) as db:
            now = datetime.now(timezone.utc)
            # Daily timer activity also expires completed filing projections while idle.
            with db:
                db.execute("DELETE FROM filing_details WHERE status NOT IN ('queued','running') AND requested_at<?", (stamp(now-timedelta(days=30)),))
            # No credentials or provider calls while the queue is idle.
            if not db.execute("SELECT 1 FROM company_context WHERE status IN ('queued','running') UNION ALL SELECT 1 FROM filing_details WHERE status IN ('queued','running') LIMIT 1").fetchone():
                return
            try:
                sec = SecClient(user_agent=os.environ.get('SEC_USER_AGENT', ''), limiter=MinimumIntervalLimiter(1))
            except ValueError:
                with db:
                    db.execute("UPDATE company_context SET status='unavailable',error='SEC identity is not configured',retry_after=? WHERE status IN ('queued','running')", (stamp(now + timedelta(minutes=15)),))
                    db.execute("UPDATE filing_details SET status='unavailable',error='SEC identity is not configured',retry_after=? WHERE status IN ('queued','running')", (stamp(now + timedelta(minutes=15)),))
                return
            from .filing_details import run_next as run_filing
            oldest = db.execute("SELECT kind FROM (SELECT 'company' kind,requested_at FROM company_context WHERE status IN ('queued','running') UNION ALL SELECT 'filing',requested_at FROM filing_details WHERE status IN ('queued','running')) ORDER BY requested_at LIMIT 1").fetchone()
            if oldest['kind'] == 'filing':
                run_filing(db, sec, now)
            else:
                run_next(db, sec, now)


if __name__ == '__main__':
    main()
