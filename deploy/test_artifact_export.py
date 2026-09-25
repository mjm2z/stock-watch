import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('artifacts',
    Path(__file__).with_name('export-stockwatch-artifacts-root.py'))
artifacts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifacts)
verify_spec = importlib.util.spec_from_file_location('artifact_verifier',
    Path(__file__).with_name('verify-artifact-export.py'))
verifier = importlib.util.module_from_spec(verify_spec)
verify_spec.loader.exec_module(verifier)


class ArtifactExportTests(unittest.TestCase):
    def test_history_content_manifest_and_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / 'source', Path(root) / 'export'
            (source / 'history').mkdir(parents=True)
            original = b'original historical data\x00\xff'
            (source / 'history/data.bin').write_bytes(original)
            artifacts.export(source, destination, os.getuid(), os.getgid())
            self.assertEqual((destination / 'data/history/data.bin').read_bytes(), original)
            manifest = json.loads((destination / 'manifest.json').read_text())
            self.assertEqual(manifest['purpose'], 'rehearsal-only')
            self.assertEqual(manifest['files'][0]['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual((destination.stat().st_mode & 0o777), 0o700)
            self.assertEqual(verifier.verify(destination)['files'], 1)
            with self.assertRaises(FileExistsError):
                artifacts.export(source, destination, os.getuid(), os.getgid())
            target = destination / 'data/history/data.bin'
            target.write_bytes(b'x' * len(original))
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                verifier.verify(destination)
            target.unlink()
            with self.assertRaisesRegex(ValueError, 'Missing'):
                verifier.verify(destination)
            target.write_bytes(original)
            (destination / 'data/extra').write_text('unexpected')
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                verifier.verify(destination)

    def test_symlink_export_fails_without_success_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            source, destination = Path(root) / 'source', Path(root) / 'export'
            source.mkdir()
            (source / 'unexpected').symlink_to('/etc/passwd')
            with self.assertRaises(RuntimeError):
                artifacts.export(source, destination, os.getuid(), os.getgid())
            self.assertFalse((destination / 'manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
