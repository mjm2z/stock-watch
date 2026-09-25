import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('compression',Path(__file__).with_name('compress-migration-snapshot.py'))
compression=importlib.util.module_from_spec(spec)
spec.loader.exec_module(compression)
unpack_spec=importlib.util.spec_from_file_location('unpack',Path(__file__).with_name('decompress-migration-snapshot.py'))
unpack=importlib.util.module_from_spec(unpack_spec)
unpack_spec.loader.exec_module(unpack)


class CompressionTests(unittest.TestCase):
    def test_roundtrip_and_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as root:
            source,manifest,target=[Path(root)/name for name in ('source.db','source.json','transfer.gz')]
            data=b'Historical records\x00\xff'*500
            source.write_bytes(data)
            manifest.write_text(json.dumps(dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())))
            result=compression.compress(source,manifest,target)
            self.assertTrue(result['roundtrip_verified'])
            self.assertEqual(gzip.decompress(target.read_bytes()),data)
            self.assertEqual(source.read_bytes(),data)
            with self.assertRaises(ValueError): compression.compress(source,manifest,target)
            restored=Path(root)/'restored.db'
            self.assertTrue(unpack.decompress(target,manifest,restored)['archive_retained'])
            self.assertEqual(restored.read_bytes(),data)
            self.assertTrue(target.exists())
            with self.assertRaises(ValueError): unpack.decompress(target,manifest,restored)
            damaged=bytearray(target.read_bytes());damaged[-1]^=1;target.write_bytes(damaged)
            with self.assertRaisesRegex(ValueError,'archive checksum mismatch'):
                unpack.decompress(target,manifest,Path(root)/'bad.db')
            self.assertFalse((Path(root)/'bad.db').exists())

    def test_changed_source_is_not_published(self):
        with tempfile.TemporaryDirectory() as root:
            source,manifest,target=[Path(root)/name for name in ('source.db','source.json','transfer.gz')]
            source.write_bytes(b'changed')
            manifest.write_text(json.dumps(dict(bytes=7,sha256='0'*64)))
            with self.assertRaises(ValueError): compression.compress(source,manifest,target)
            self.assertFalse(target.exists())


if __name__ == '__main__': unittest.main()
