import importlib.util,json,sqlite3,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('lean_history_verification',Path(__file__).resolve().parents[2]/'deploy/verify-lean-history.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
class HistoryVerificationTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        for name in ['016_systems.sql','027_lean_comparisons.sql']:self.db.executescript((Path(__file__).resolve().parents[1]/'migrations'/name).read_text())
        self.db.execute('INSERT INTO system_versions VALUES (?,?,?,?,?,?,?)',(helper.VERSION,'bitcoin','trend','{}','hash','now',''))
        for identifier in ['dataset','other']:self.db.execute('INSERT INTO system_datasets VALUES (?,?,?,?,?,?)',(identifier,'bitcoin','unused',identifier,'{}','now'))
        self.db.commit()
    def tearDown(self):self.db.close()
    def test_stable_identity_creates_one_research_job_and_no_deployment(self):
        helper.queue(self.db,'dataset');helper.queue(self.db,'dataset')
        self.assertEqual(self.db.execute('SELECT count(*) FROM lean_comparisons').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM system_audit').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM system_deployments').fetchone()[0],0)
    def test_conflicting_dataset_cannot_replace_existing_research(self):
        helper.queue(self.db,'dataset')
        with self.assertRaisesRegex(ValueError,'identity conflict'):helper.queue(self.db,'other')
        self.assertEqual(self.db.execute('SELECT dataset_id FROM lean_comparisons').fetchone()[0],'dataset')
