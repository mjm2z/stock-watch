import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cleanup', Path(__file__).with_name('cleanup-storage.py'))
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class CleanupTests(unittest.TestCase):
    def test_keeps_current_two_rollbacks_completed_backups_and_unrelated_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, staging, backups = root/'opt/stock-watch', root/'staging', root/'backups'
            for path in (runtime, staging, backups): path.mkdir(parents=True)
            old = []
            for day in range(1, 5):
                path = runtime.parent/f'stock-watch.before-202609{day:02d}T010000Z'
                path.mkdir(); old.append(path)
                (path/'installed-release.json').write_text(json.dumps({'revision':str(day)*40}))
                release = staging/(str(day)*12); release.mkdir()
                (release/'reviewed-release.json').write_text('{}')
            (runtime/'installed-release.json').write_text(json.dumps({'revision':'a'*40,'previous_runtime':str(old[-1])}))
            active = staging/('a'*12); active.mkdir()
            unrelated = staging/'operator-notes'; unrelated.mkdir()
            symlink = staging/('f'*12); symlink.symlink_to(unrelated, target_is_directory=True)
            final = backups/'stock-watch-20260928T043401555281Z.db'; final.write_bytes(b'keep')
            tmp = backups/'.stock-watch-20260930T043452553216Z.db.tmp'; tmp.write_bytes(b'old')
            plan = cleanup.candidates(runtime, staging, backups, now=10**12)
            paths = {e['path'] for e in plan['candidates']}
            self.assertIn(str(old[0]), paths); self.assertNotIn(str(old[-1]), paths)
            self.assertNotIn(str(old[-2]), paths); self.assertNotIn(str(active), paths)
            self.assertNotIn(str(final), paths); self.assertIn(str(tmp), paths)
            self.assertNotIn(str(unrelated), paths); self.assertNotIn(str(symlink), paths)
            with patch.object(cleanup, 'in_use', return_value=set()): cleanup.remove_plan(plan)
            self.assertTrue(final.exists()); self.assertTrue(runtime.exists()); self.assertTrue(old[-1].exists())

    def test_refuses_open_handles_and_changed_candidates_before_deleting(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'candidate'; p.write_text('original'); s=p.stat()
            plan={'candidates':[{'path':str(p),'kind':'abandoned-backup','identity':[s.st_dev,s.st_ino,s.st_mtime_ns]}]}
            with patch.object(cleanup,'in_use',return_value={str(p)}):
                with self.assertRaisesRegex(RuntimeError,'still in use'):cleanup.remove_plan(plan)
            self.assertTrue(p.exists()); p.write_text('changed')
            with patch.object(cleanup,'in_use',return_value=set()):
                with self.assertRaisesRegex(RuntimeError,'changed'):cleanup.remove_plan(plan)
            self.assertTrue(p.exists())

    def test_path_prefix_does_not_match_siblings(self):
        self.assertTrue(cleanup.under('/old/release/file','/old/release'))
        self.assertFalse(cleanup.under('/old/release-new/file','/old/release'))

class RecoveryRetentionTests(unittest.TestCase):
    def test_keeps_two_newest_verified_and_ignores_partial_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            snapshots=[]
            for day in range(1,6):
                p=root/f'202609{day:02d}T010000Z';p.mkdir();snapshots.append(p)
                (p/'stock-watch.db').write_bytes(b'copy')
                (p/'backup-verified.json').write_text(json.dumps({'verified':day != 5}))
                (p/'config').mkdir()
            rows,kept=cleanup.recovery_candidates(root)
            self.assertEqual(kept,[str(snapshots[3]),str(snapshots[2])])
            self.assertEqual({r['path'] for r in rows},{str(snapshots[0]/'stock-watch.db'),str(snapshots[1]/'stock-watch.db')})
            with patch.object(cleanup,'in_use',return_value=set()):cleanup.remove_plan({'candidates':rows})
            self.assertTrue((snapshots[0]/'config').is_dir())
            self.assertTrue((snapshots[4]/'stock-watch.db').exists())
            self.assertTrue((snapshots[3]/'stock-watch.db').exists())
            rows,_=cleanup.recovery_candidates(root);self.assertEqual(rows,[])
