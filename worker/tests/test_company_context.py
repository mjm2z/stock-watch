import json
import sqlite3
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from stock_watch_worker.company_context import project, filing_url, run_next, collect

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)
ACC = '0000320193-26-000001'
SUBMISSIONS = {'name': 'Example Inc', 'filings': {'recent': {
    'accessionNumber': [ACC], 'form': ['8-K'], 'filingDate': ['2026-09-30'],
    'acceptanceDateTime': ['2026-09-30T20:00:00Z'], 'reportDate': ['2026-09-29'],
    'items': ['2.02,9.01'], 'primaryDocDescription': ['Results'],
}}}

def fact(value=100, **extra):
    return {'start': '2025-01-01', 'end': '2025-12-31', 'filed': '2026-02-01',
            'form': '10-K', 'accn': ACC, 'val': value, **extra}

def facts(entries):
    return {'facts': {'us-gaap': {'Revenues': {'units': {'USD': entries}}}}}

class CompanyContextTests(unittest.TestCase):
    def test_reports_annual_only_and_keeps_amendment_provenance(self):
        data = facts([fact(), fact(120, filed='2026-03-01', form='10-K/A'),
                      fact(999, start='2026-01-01', end='2026-06-30', filed='2026-07-01', form='10-Q'),
                      fact(9999, filed='2027-01-01')])
        value = project(SUBMISSIONS, data, '320193', 'AAPL', 'company', NOW)
        self.assertEqual(value['metrics'][0]['value'], 120)
        self.assertEqual(value['metrics'][0]['filed'], '2026-03-01')
        self.assertTrue(value['filings'][0]['earningsRelated'])
        self.assertEqual(value['filings'][0]['accepted'], '2026-09-30T20:00:00Z')
        self.assertEqual(value['metrics'][1]['value'], None)

    def test_funds_have_no_corporate_metrics_and_urls_are_restricted(self):
        value = project({**SUBMISSIONS, 'sic': '6722'}, facts([fact()]), '320193', 'FUND', 'company', NOW)
        self.assertEqual(value['kind'], 'fund')
        self.assertEqual(value['metrics'], [])
        self.assertIsNone(filing_url('320193', '../../bad'))
        self.assertIsNone(filing_url('https://bad', ACC))

    def test_spy_trust_has_fund_view_even_without_sic_or_series(self):
        value = project(SUBMISSIONS, facts([fact()]), '0000884394', 'SPY', 'company', NOW)
        self.assertEqual(value['kind'], 'fund')
        self.assertEqual(value['metrics'], [])

    def test_bad_units_nonfinite_values_and_ytd_are_not_metrics(self):
        value = project(SUBMISSIONS, facts([fact(float('nan')), fact(True), fact(10, start='2025-07-01')]), '320193', 'AAPL', 'company', NOW)
        self.assertIsNone(value['metrics'][0]['value'])
        self.assertEqual(len(value['metrics']), 5)

    def db(self):
        db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
        db.executescript((Path(__file__).parents[1] / 'migrations/025_company_context.sql').read_text())
        return db

    def test_interruption_recovery_and_failure_preserve_last_payload_with_cooldown(self):
        db = self.db()
        db.execute("INSERT INTO company_context(symbol,status,requested_at,payload_json) VALUES ('AAPL','running',?,'{\"name\":\"old\"}')", (NOW.isoformat(),)); db.commit()
        self.assertFalse(run_next(db, Mock(), NOW))
        self.assertEqual(db.execute('SELECT status FROM company_context').fetchone()[0], 'unavailable')
        db.execute("UPDATE company_context SET status='queued'"); db.commit()
        with patch('stock_watch_worker.company_context.collect', side_effect=RuntimeError('secret provider body')):
            self.assertTrue(run_next(db, Mock(), NOW))
        row = db.execute('SELECT * FROM company_context').fetchone()
        self.assertEqual(row['status'], 'unavailable')
        self.assertEqual(json.loads(row['payload_json'])['name'], 'old')
        self.assertNotIn('secret', row['error'])
        self.assertEqual(datetime.fromisoformat(row['retry_after']), NOW + timedelta(minutes=15))
        db.close()

    def test_collection_reuses_recent_companyfacts_without_broker_calls(self):
        db = self.db()
        db.executescript('CREATE TABLE instruments(id INTEGER, symbol TEXT,cik TEXT); CREATE TABLE company_fact_documents(instrument_id INTEGER,facts_json TEXT,captured_at TEXT);')
        db.execute("INSERT INTO instruments VALUES(1,'AAPL','320193')")
        db.execute('INSERT INTO company_fact_documents VALUES(1,?,?)',(json.dumps(facts([fact()])), NOW.isoformat()))
        sec = Mock(); sec.get_submissions.return_value = SUBMISSIONS
        result = collect(db, sec, 'AAPL', NOW)
        self.assertEqual(result['metrics'][0]['value'],100)
        sec.get_company_facts.assert_not_called()
        sec.get_company_tickers.assert_not_called()
        db.close()

if __name__ == '__main__': unittest.main()
