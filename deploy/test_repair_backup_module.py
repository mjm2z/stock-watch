import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('repair',Path(__file__).with_name('repair-backup-module.py'))
repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)

class BackupModuleRepairTests(unittest.TestCase):
    def test_active_backup_and_unknown_revision_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'source-revision.txt').write_text(repair.REVISION)
            with patch.object(repair,'ROOT',root),patch.object(repair.os,'geteuid',return_value=0),patch.object(repair.subprocess,'check_output',return_value='active\n'):
                with self.assertRaisesRegex(SystemExit,'active backup'):repair.main()
                (root/'source-revision.txt').write_text('unknown')
                with self.assertRaisesRegex(SystemExit,'revision changed'):repair.main()

    def test_unknown_module_hash_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'source-revision.txt').write_text(repair.REVISION)
            staged=root/'backup.py';staged.write_text('new=1\n')
            (root/'backup.sha256').write_text(hashlib.sha256(staged.read_bytes()).hexdigest())
            for name in ('worker/src/stock_watch_worker/backup.py','.venv/lib/python3.12/site-packages/stock_watch_worker/backup.py'):
                p=root/name;p.parent.mkdir(parents=True);p.write_text('unknown=1\n')
            with patch.object(repair,'ROOT',root),patch.object(repair,'__file__',str(root/'installer.py')),patch.object(repair.os,'geteuid',return_value=0),patch.object(repair.subprocess,'check_output',return_value='failed\n'):
                with self.assertRaisesRegex(SystemExit,'hash mismatch'):repair.main()
            self.assertEqual((root/'worker/src/stock_watch_worker/backup.py').read_text(),'unknown=1\n')
