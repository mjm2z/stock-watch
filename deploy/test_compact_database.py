import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('compact',Path(__file__).with_name('compact-database.py'))
compact=importlib.util.module_from_spec(spec);spec.loader.exec_module(compact)

class CompactionTests(unittest.TestCase):
    def test_reclaims_free_pages_preserving_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'db'
            with sqlite3.connect(p) as c:
                c.executescript("CREATE TABLE schema_migrations(version TEXT); INSERT INTO schema_migrations VALUES('023_company_fact_storage'); CREATE TABLE company_fact_observations(id INTEGER PRIMARY KEY); INSERT INTO company_fact_observations VALUES(7); CREATE TABLE company_fact_contents(hash TEXT PRIMARY KEY, payload TEXT); INSERT INTO company_fact_contents VALUES('kept','evidence'); CREATE TABLE wasted(payload BLOB); INSERT INTO wasted VALUES(zeroblob(4000000)); DROP TABLE wasted;")
            with patch.object(compact.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()):
                result=compact.compact(p)
            self.assertGreater(result['reclaimed_bytes'],3000000)
            with sqlite3.connect(p) as c:
                self.assertEqual(c.execute('SELECT id FROM company_fact_observations').fetchall(),[(7,)])
                self.assertEqual(c.execute('SELECT payload FROM company_fact_contents').fetchone()[0],'evidence')

    def test_low_space_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'db'
            with sqlite3.connect(p) as c:c.executescript("CREATE TABLE schema_migrations(version TEXT); INSERT INTO schema_migrations VALUES('023_company_fact_storage');")
            before=p.read_bytes()
            with patch.object(compact.shutil,'disk_usage',return_value=type('Disk',(),{'free':0})()):
                with self.assertRaisesRegex(RuntimeError,'free bytes'):compact.compact(p)
            self.assertEqual(before,p.read_bytes())
