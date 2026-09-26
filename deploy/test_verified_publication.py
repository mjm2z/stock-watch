import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('publish',Path(__file__).with_name('publish-stockwatch-export-root.py'))
publish=importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class VerifiedTransfer(unittest.TestCase):
    def test_both_recovery_archive_and_database_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            database=b'fully verified source snapshot'
            archive=b'verified compressed archive'
            manifest=dict(bytes=len(database),sha256=hashlib.sha256(database).hexdigest())
            (root/'stock-watch.db').write_bytes(database)
            (root/'stock-watch.db.gz').write_bytes(archive)
            (root/'stock-watch.db.gz.json').write_text(json.dumps(dict(
                roundtrip_verified=True,source_bytes=manifest['bytes'],source_sha256=manifest['sha256'],
                compressed_bytes=len(archive),compressed_sha256=hashlib.sha256(archive).hexdigest())))
            publish.verify_transfer(root,manifest)
            (root/'stock-watch.db').write_bytes(b'X'+database[1:])
            with self.assertRaisesRegex(RuntimeError,'Decompressed'):
                publish.verify_transfer(root,manifest)
            (root/'stock-watch.db').write_bytes(database)
            (root/'stock-watch.db.gz').write_bytes(b'X'+archive[1:])
            with self.assertRaisesRegex(RuntimeError,'Compressed'):
                publish.verify_transfer(root,manifest)
            self.assertTrue((root/'stock-watch.db').exists())


if __name__=='__main__': unittest.main()
