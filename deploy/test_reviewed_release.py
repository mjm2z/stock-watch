import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('release', Path(__file__).with_name('install-reviewed-release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseGuards(unittest.TestCase):
    def test_corrupted_release_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / 'payload'
            path.write_bytes(b'reviewed')
            manifest = {'files': {'payload': hashlib.sha256(b'reviewed').hexdigest()}}
            release.verify_files(root, manifest)
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'Staged release changed'):
                release.verify_files(root, manifest)

    def test_manifest_cannot_escape_release(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, 'Unsafe release manifest path'):
                release.verify_files(Path(directory).resolve(), {'files': {'../outside': 'unused'}})


if __name__ == '__main__':
    unittest.main()
