import json
import tempfile
import unittest
from pathlib import Path
from stock_watch_worker.database import connect, apply_migrations
from stock_watch_worker.systems.engine import canonical
from stock_watch_worker.systems.inspection import execute_demo
from stock_watch_worker.systems.workspace import run_workspace


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'app.db'
        self.db = connect(self.path); apply_migrations(self.db)

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def demo(self):
        with self.db:
            self.db.execute("INSERT INTO workspace_jobs(id,kind,payload_json,created_at) VALUES ('demo','research_demo',?,?)",(canonical({'asset':'bitcoin'}),'2026-01-01T00:00:00Z'))
        run_workspace(self.db,self.path)
        row = self.db.execute("SELECT * FROM workspace_jobs WHERE id='demo'").fetchone()
        self.assertEqual(row['status'],'succeeded',row['error'])
        run_workspace(self.db,self.path); run_workspace(self.db,self.path)

    def test_demo_runs_without_executable_versions_or_authority(self):
        self.demo()
        jobs = self.db.execute("SELECT * FROM workspace_jobs WHERE kind='preview'").fetchall()
        for job in jobs:
            self.assertEqual(job['status'],'succeeded',job['error'])
            result = json.loads(self.db.execute('SELECT result_json FROM research_previews WHERE id=?',(job['id'],)).fetchone()[0])
            self.assertEqual(result['evidence_class'],'demonstration fixture')
            self.assertEqual(result['continuous']['starting_cash'],1000)
            self.assertEqual(result['authority'],'research-only')
            self.assertTrue(result['continuous']['equity_curve'])
            self.assertIn('drawdown',result['continuous']['equity_curve'][-1])
        for table in ('system_versions','system_deployments','btc_allocations','btc_enrollments','btc_orders','system_orders','paper_authorizations'):
            self.assertEqual(self.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
        self.assertEqual(self.db.execute('SELECT count(*) FROM research_access').fetchone()[0],2)

    def test_reused_cache_records_exposure_and_retains_original_age(self):
        self.demo()
        row = self.db.execute("SELECT * FROM workspace_jobs WHERE id='demo-baseline'").fetchone()
        with self.db:
            self.db.execute('INSERT INTO workspace_jobs(id,kind,payload_json,created_at) VALUES (?,?,?,?)',('retry','preview',row['payload_json'],row['created_at']))
            sid = json.loads(row['payload_json'])['snapshot']
            self.db.execute('INSERT INTO research_previews(id,snapshot_id,created_at) VALUES (?,?,?)',('retry',sid,row['created_at']))
        run_workspace(self.db,self.path)
        result = json.loads(self.db.execute("SELECT result_json FROM research_previews WHERE id='retry'").fetchone()[0])
        self.assertEqual(result['reused_from'],'demo-baseline')
        self.assertFalse(result['independent_evidence'])
        self.assertEqual(result['prior_interval_inspections'],2)

    def test_mismatched_timeframe_and_hash_fail_without_authority(self):
        self.demo()
        row = self.db.execute("SELECT * FROM workspace_jobs WHERE id='demo-baseline'").fetchone()
        payload = json.loads(row['payload_json'])
        data = self.db.execute('SELECT path FROM system_datasets WHERE id=?',(payload['dataset'],)).fetchone()
        Path(data['path']).write_text('{}')
        with self.db:
            self.db.execute('INSERT INTO workspace_jobs(id,kind,payload_json,created_at) VALUES (?,?,?,?)',('bad','preview',row['payload_json'],row['created_at']))
            self.db.execute('INSERT INTO research_previews(id,snapshot_id,created_at) VALUES (?,?,?)',('bad',payload['snapshot'],row['created_at']))
        run_workspace(self.db,self.path)
        job = self.db.execute("SELECT * FROM workspace_jobs WHERE id='bad'").fetchone()
        self.assertEqual(job['status'],'failed')
        self.assertIn('hash mismatch',job['error'])
