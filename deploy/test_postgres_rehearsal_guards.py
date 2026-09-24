import json
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('postgres-rehearsal-restore.mjs')


class PostgresRehearsalGuards(unittest.TestCase):
    def run_guard(self, prefix, database):
        env = dict(os.environ, DATABASE_URL=f'postgresql://test:unused@127.0.0.1:5432/{database}')
        return subprocess.run(['node', str(SCRIPT), str(SCRIPT.parent),
                               str(prefix), str(prefix) + '-inspection'],
                              env=env, capture_output=True, text=True)

    def test_production_database_is_refused_before_any_connection(self):
        result = self.run_guard('/does-not-exist', 'jobwatch')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Only a loopback rehearsal database is permitted', result.stderr)

    def test_changed_dump_is_refused_before_any_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)/'snapshot'
            prefix.with_suffix('.dump').write_bytes(b'changed snapshot')
            prefix.with_suffix('.json').write_text(json.dumps({
                'format':3, 'serialization':'UTC/ISO-YMD/postgres/float3/PK',
                'tables':{}, 'dump_sha256':'0'*64}))
            result = self.run_guard(prefix, 'jobwatch_rehearsal')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Transferred dump checksum mismatch', result.stderr)


if __name__ == '__main__':
    unittest.main()
