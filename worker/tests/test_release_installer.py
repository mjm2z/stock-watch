import importlib.util
from pathlib import Path
import unittest
import sqlite3
import tempfile
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('reviewed_installer',Path(__file__).resolve().parents[2]/'deploy/install-reviewed-release.py')
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

class InstallerDrainTests(unittest.TestCase):
    def test_supervised_installer_does_not_wait_on_itself(self):
        lines=['stock-watch-release-example.service transient -',
               'stock-watch-web.service enabled enabled',
               'stock-watch-worker.service static -',
               'stock-watch-worker.timer enabled enabled']
        with patch.object(installer,'output',side_effect=['4242','5000']):
            self.assertEqual(installer.drain_services(lines,4242),['stock-watch-worker.service'])
    def test_other_running_services_are_not_exempted_by_name(self):
        lines=['stock-watch-release-other.service transient -',
               'stock-watch-discovery.service static -']
        with patch.object(installer,'output',side_effect=['6000','0']):
            self.assertEqual(installer.drain_services(lines,4242),[
                'stock-watch-release-other.service','stock-watch-discovery.service'])

class DeploymentPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.runtime = self.root / 'source', self.root / 'runtime'
        for directory in (self.source, self.runtime):
            (directory / 'worker/migrations').mkdir(parents=True)
            (directory / 'worker/migrations/001_base.sql').write_text('CREATE TABLE original(id);')
            for name in ('database.py', 'systems/cli.py'):
                path = directory / 'worker/src/stock_watch_worker' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# existing initialization')
        self.database = self.root / 'state.db'
        with sqlite3.connect(self.database) as db:
            db.executescript("CREATE TABLE schema_migrations(version TEXT); INSERT INTO schema_migrations VALUES ('001_base'); CREATE TABLE paper_orders(id); INSERT INTO paper_orders VALUES (42);")

    def plan(self, force=False):
        return installer.deployment_plan(self.source, self.runtime, self.database, force)

    def test_unchanged_history_selects_code_only(self):
        self.assertEqual(self.plan()['mode'], 'code-only')

    def test_pending_migration_requires_backup(self):
        (self.source / 'worker/migrations/002_new.sql').write_text('CREATE TABLE next(id);')
        self.assertEqual(self.plan()['mode'], 'database')
        self.assertEqual(self.plan()['pending_migrations'], ['002_new'])

    def test_edited_applied_migration_rejected_even_with_force(self):
        (self.source / 'worker/migrations/001_base.sql').write_text('DROP TABLE original;')
        for force in (False, True):
            with self.assertRaisesRegex(RuntimeError, 'Applied migration'):
                self.plan(force)

    def test_removed_applied_migration_rejected(self):
        (self.source / 'worker/migrations/001_base.sql').unlink()
        (self.source / 'worker/migrations/002_new.sql').write_text('-- new')
        with self.assertRaisesRegex(RuntimeError, 'Applied migration'):
            self.plan()

    def test_unknown_database_migration_rejects_downgrade(self):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO schema_migrations VALUES ('999_future')")
        with self.assertRaisesRegex(RuntimeError, '999_future'):
            self.plan()

    def test_changed_initialization_requires_backup(self):
        (self.source / 'worker/src/stock_watch_worker/systems/cli.py').write_text('# changed seeding')
        self.assertEqual(self.plan()['mode'], 'database')

    def test_explicit_backup_override(self):
        self.assertEqual(self.plan(True)['mode'], 'database')

    def test_code_only_does_not_copy_or_modify_database(self):
        recovery = self.root / 'recovery'
        recovery.mkdir()
        before_bytes = self.database.read_bytes()
        counts, _ = installer.preserve_database(self.database, recovery, self.plan())
        self.assertEqual(counts['paper_orders'], 1)
        self.assertEqual(list(recovery.iterdir()), [])
        self.assertEqual(self.database.read_bytes(), before_bytes)

    def test_database_mode_creates_verified_usable_recovery(self):
        recovery = self.root / 'recovery'
        recovery.mkdir()
        installer.preserve_database(self.database, recovery, self.plan(True))
        self.assertTrue((recovery / 'backup-verified.json').is_file())
        with sqlite3.connect(recovery / 'stock-watch.db') as db:
            self.assertEqual(db.execute('SELECT id FROM paper_orders').fetchall(), [(42,)])

if __name__=='__main__':unittest.main()
