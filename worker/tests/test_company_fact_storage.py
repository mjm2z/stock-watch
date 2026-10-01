import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from stock_watch_worker.database import apply_migrations, MIGRATIONS_DIR
from stock_watch_worker.ingestion import persist_company_facts


class CompanyFactStorageTests(unittest.TestCase):
    def legacy(self, directory):
        legacy = Path(directory)/'migrations'; legacy.mkdir()
        for path in MIGRATIONS_DIR.glob('*.sql'):
            if path.name < '023': shutil.copyfile(path, legacy/path.name)
        connection = sqlite3.connect(':memory:'); connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        apply_migrations(connection, legacy)
        connection.execute("INSERT INTO instruments(id,symbol,name) VALUES(1,'AAPL','Apple')")
        connection.commit()
        return connection

    def test_preserves_ids_metadata_and_payloads_and_future_writes_deduplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            c=self.legacy(directory)
            payload=json.dumps({'facts':{'example':1}},sort_keys=True,separators=(',',':'))
            sha=hashlib.sha256(payload.encode()).hexdigest()
            for identifier in (4,9,12):
                c.execute('INSERT INTO company_fact_documents(id,instrument_id,captured_at,content_sha256,facts_json) VALUES(?,1,?,?,?)',(identifier,f'2026-01-{identifier:02d}',sha,payload))
            before=[tuple(r) for r in c.execute('SELECT * FROM company_fact_documents ORDER BY id')]
            c.commit();apply_migrations(c)
            self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM company_fact_documents ORDER BY id')])
            self.assertEqual(c.execute('SELECT count(*) FROM company_fact_contents').fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            result=persist_company_facts(c,symbol='AAPL',captured_at='2026-02-01',company_facts=json.loads(payload))
            self.assertEqual(result.document_id,13)
            self.assertEqual(c.execute('SELECT count(*) FROM company_fact_contents').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM company_fact_observations').fetchone()[0],4)
            again=persist_company_facts(c,symbol='AAPL',captured_at='2026-02-01',company_facts=json.loads(payload))
            self.assertEqual(again.document_id,result.document_id)
            persist_company_facts(c,symbol='AAPL',captured_at='2026-03-01',company_facts={'facts':{'example':2}})
            self.assertEqual(c.execute('SELECT count(*) FROM company_fact_contents').fetchone()[0],2)
            c.close()

    def test_conflicting_historical_hash_aborts_entire_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            c=self.legacy(directory)
            for i in (1,2):c.execute('INSERT INTO company_fact_documents(instrument_id,captured_at,content_sha256,facts_json) VALUES(1,?,?,?)',(str(i),'same',json.dumps({'value':i})))
            c.commit()
            with self.assertRaises(sqlite3.IntegrityError):apply_migrations(c)
            self.assertEqual(c.execute("SELECT type FROM sqlite_master WHERE name='company_fact_documents'").fetchone()[0],'table')
            self.assertEqual(c.execute('SELECT count(*) FROM company_fact_documents').fetchone()[0],2)
            self.assertIsNone(c.execute("SELECT 1 FROM schema_migrations WHERE version='023_company_fact_storage'").fetchone())
            c.close()

    def test_new_captured_date_has_no_duplicated_payload_and_old_id_still_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            c=self.legacy(directory);apply_migrations(c)
            a=persist_company_facts(c,symbol='AAPL',captured_at='2026-01-01',company_facts={'facts':{'value':'first'}})
            b=persist_company_facts(c,symbol='AAPL',captured_at='2026-02-01',company_facts={'facts':{'value':'second'}})
            d=persist_company_facts(c,symbol='AAPL',captured_at='2026-03-01',company_facts={'facts':{'value':'first'}})
            self.assertNotEqual(a.document_id,d.document_id)
            self.assertEqual(c.execute('SELECT count(*) FROM company_fact_contents').fetchone()[0],2)
            self.assertEqual(json.loads(c.execute('SELECT facts_json FROM company_fact_documents WHERE id=?',(a.document_id,)).fetchone()[0]),{'facts':{'value':'first'}})
            c.close()
