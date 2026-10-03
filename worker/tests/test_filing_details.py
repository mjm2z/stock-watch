import unittest
from stock_watch_worker.filing_details import document_url, extract, exact_facts

class FilingDetailsTests(unittest.TestCase):
    def test_identity_and_formats(self):
        self.assertIn('/123/000000012326000001/report.htm',document_url('123','0000000123-26-000001','report.htm'))
        for name in ('../a.htm','https://evil/a.htm','a.pdf','a.htm?x=1'):
            with self.assertRaises(ValueError): document_url('123','0000000123-26-000001',name)
    def test_hidden_content_and_plain_text(self):
        result=extract('<p>Visible &amp; safe</p><script>bad</script><ix:hidden>secret</ix:hidden><div style="display: none"><span>hidden</span></div><p>End</p>')
        self.assertEqual(result['text'],'Visible & safe\nEnd')
    def test_bound(self):
        self.assertLessEqual(len(extract('é'*500000)['text'].encode()),180000)
    def test_exact_accession(self):
        facts={'facts':{'us-gaap':{'Revenues':{'units':{'USD':[{'accn':'original','val':10,'end':'2025-12-31'},{'accn':'amendment','val':20,'end':'2025-12-31'}]}}}}}
        rows=exact_facts(facts,'original')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['value'],10)

    def test_sections(self):
        result=extract('<p>Item 1. Business</p><p>'+('Business facts. '*30)+'</p>')
        self.assertEqual(result['sections'][0]['title'],'Item 1. Business')
    def test_worker_preserves_failed_projection_and_recovers(self):
        import sqlite3, json
        from pathlib import Path
        from datetime import datetime, timezone
        from unittest.mock import Mock, patch
        from stock_watch_worker.filing_details import run_next
        db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
        root=Path(__file__).resolve().parents[1]/'migrations'
        for name in ('025_company_context.sql','026_filing_details.sql'): db.executescript((root/name).read_text())
        acc='0000000123-26-000001'
        issuer={'cik':'123','kind':'fund','filings':[{'accession':acc,'primaryDocument':'report.htm'}]}
        db.execute("INSERT INTO company_context(symbol,status,requested_at,payload_json) VALUES ('SPY','ready','2026-10-02',?)",(json.dumps(issuer),))
        db.execute("INSERT INTO filing_details(symbol,accession,status,requested_at) VALUES ('SPY',?,'queued','2026-10-02')",(acc,))
        now=datetime(2026,10,2,tzinfo=timezone.utc)
        with patch('stock_watch_worker.filing_details.download',return_value='<p>source</p>'):
            self.assertTrue(run_next(db,Mock(),now))
        original=db.execute('SELECT payload_json FROM filing_details').fetchone()[0]
        db.execute("UPDATE filing_details SET status='running'")
        run_next(db,Mock(),now)
        row=db.execute('SELECT * FROM filing_details').fetchone()
        self.assertEqual(row['status'],'unavailable')
        self.assertEqual(row['payload_json'],original)
        db.close()
