import importlib.util
from pathlib import Path
import shlex
import unittest

spec = importlib.util.spec_from_file_location('exporter',
    Path(__file__).with_name('restricted-app-backup-export.py'))
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class BackupExportTests(unittest.TestCase):
    def test_existing_absolute_client_path_is_anchored_to_export_root(self):
        root, command = exporter.restricted_command('homeops',
            'rsync --server --sender -logDtprze.iLsfxCIvu . /home/mjm2z/.local/state/home-ops/backups/')
        self.assertEqual(root, exporter.ROOTS['homeops'])
        self.assertEqual(shlex.split(command)[-1], '/')

    def test_shell_commands_and_write_side_are_refused(self):
        for command in ['id', 'sh -c id', 'rsync --server -logDt . /', '']:
            with self.assertRaises(ValueError):
                exporter.restricted_command('homeops', command)


if __name__ == '__main__':
    unittest.main()
