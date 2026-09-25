import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backups', Path(__file__).with_name('app-postgres-backups.py'))
backups = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backups)


class PostgresBundleTests(unittest.TestCase):
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
