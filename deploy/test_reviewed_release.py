import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('release', Path(__file__).with_name('install-reviewed-release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseGuards(unittest.TestCase):
    def test_only_verified_environment_example_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            example = root / '.env.example'
            example.write_bytes(b'API_KEY=\n')
            manifest = {'files': {'.env.example': hashlib.sha256(example.read_bytes()).hexdigest()}}
            release.verify_environment_files(root, manifest)
            for name in ('.env', '.env.local', '.env.production', '.env.backup'):
                secret = root / name
                secret.write_bytes(b'private')
                with self.assertRaisesRegex(RuntimeError, 'unapproved environment file'):
                    release.verify_environment_files(root, manifest)
                secret.unlink()
            example.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'differs from reviewed source'):
                release.verify_environment_files(root, manifest)
            with self.assertRaisesRegex(RuntimeError, 'unapproved environment file'):
                release.verify_environment_files(root, {'files': {}})

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
