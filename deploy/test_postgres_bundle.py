import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backups', Path(__file__).with_name('app-postgres-backups.py'))
backups = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backups)


class PostgresBundleTests(unittest.TestCase):
    def setUp(self):
        clock=patch.object(backups,'datetime',wraps=datetime)
        self.clock=clock.start();self.addCleanup(clock.stop)
        self.clock.now.return_value=datetime(2026,11,1,12,tzinfo=timezone.utc)

    def history(self, root, count=40):
        for offset in range(count):
            captured=backups.datetime.now(timezone.utc)-timedelta(days=offset)
            folder=root/captured.strftime('%Y%m%dT%H%M%S%fZ');folder.mkdir()
            metadata=self.bundle(folder);metadata['recovery_point_at']=captured.isoformat()
            (folder/'bundle.json').write_text(json.dumps(metadata))

    def policy(self):
        return dict(enabled=True,pins=[],restore_proof=dict(verified=True,
            verification='isolated_restore_and_all_table_fingerprints',apps=['jobwatch','radar']))

    def test_retention_requires_restore_and_preserves_pins(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.history(root)
            policy=self.policy();policy['pins']=[min(p.name for p in root.iterdir())]
            value=backups.retention(root,policy)
            self.assertGreater(value['reclaimable_bytes'],0)
            self.assertEqual(value['retained_count'],11)
            with self.assertRaisesRegex(RuntimeError,'restore receipt'):
                backups.retention(root,{},True)
            self.assertEqual(len(list(root.iterdir())),40)
            with patch.object(backups.subprocess,'run'):
                backups.retention(root,policy,True)
            self.assertEqual(len(list(root.iterdir())),11)

    def test_weekly_overlap_on_monday(self):
        self.clock.now.return_value=datetime(2026,11,2,12,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.history(root)
            policy=self.policy();policy['pins']=[min(p.name for p in root.iterdir())]
            self.assertEqual(backups.retention(root,policy)['retained_count'],10)

    def test_corruption_blocks_cleanup_before_first_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.history(root,12)
            (min(root.iterdir())/'radar.dump').write_bytes(b'corrupt')
            with patch.object(backups.subprocess,'run'):
                with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                    backups.retention(root,self.policy(),True)
            self.assertEqual(len(list(root.iterdir())),12)

    def test_unknown_bundle_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.history(root,12)
            oldest=min(root.iterdir());(oldest/'personal.txt').write_text('preserve')
            value=backups.retention(root,self.policy())
            item=next(i for i in value['items'] if i['name']==oldest.name)
            self.assertEqual(item['action'],'keep')
            self.assertIn('unrecognized',item['reason'])

    def test_stale_latest_blocks_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.history(root,12)
            for path in root.iterdir():
                metadata=json.loads((path/'bundle.json').read_text())
                metadata['recovery_point_at']=(datetime.fromisoformat(metadata['recovery_point_at'])-timedelta(days=3)).isoformat()
                (path/'bundle.json').write_text(json.dumps(metadata))
            with self.assertRaisesRegex(RuntimeError,'fresh recovery'):
                backups.retention(root,self.policy(),True)

    def bundle(self, directory):
        for app, table in [('jobwatch','jobs'),('radar','raw_posts')]:
            (directory/(app+'.dump')).write_bytes(b'fixture archive')
            manifest = dict(format=3, tables={f'"public"."{table}"': {'rows':42,'sha256':'test'}},
                            dump_sha256=backups.checksum(directory/(app+'.dump')))
            (directory/(app+'.json')).write_text(json.dumps(manifest))
        metadata = dict(format=1, recovery_point_at=backups.now(), files={
            p.name: backups.checksum(p) for p in directory.iterdir()})
        (directory/'bundle.json').write_text(json.dumps(metadata))
        return metadata

    def test_expired_verification_budget_stops_before_archive_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.bundle(root)
            with patch.object(backups.subprocess,'run') as archive:
                with self.assertRaisesRegex(TimeoutError,'deadline'):
                    backups.verify_bundle(root,deadline=backups.time.monotonic()-1)
                archive.assert_not_called()

    def test_checksum_corruption_rejected_before_archive_tool(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            self.bundle(directory)
            (directory/'radar.dump').write_bytes(b'corrupt archive')
            with patch.object(backups.subprocess,'run') as archive:
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    backups.verify_bundle(directory)
                archive.assert_not_called()

    def test_requires_both_apps_and_checks_each_archive(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            metadata = self.bundle(directory)
            with patch.object(backups.subprocess,'run') as archive:
                self.assertEqual(backups.verify_bundle(directory), metadata)
                self.assertEqual(archive.call_count, 2)
            del metadata['files']['radar.json']
            (directory/'bundle.json').write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                backups.verify_bundle(directory)


if __name__ == '__main__':
    unittest.main()
