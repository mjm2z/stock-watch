import os
from pathlib import Path
import socket
import subprocess
import unittest

SCRIPT = Path(__file__).with_name('postgres-final-restore.mjs')


class FinalRestoreGuards(unittest.TestCase):
    def test_missing_source_stop_confirmation_fails_before_database_access(self):
        result = subprocess.run(['node',str(SCRIPT),'/missing/app','/missing/dump','/missing/output'],
            env=dict(os.environ,DATABASE_URL='postgresql://unused:unused@127.0.0.1:1/jobwatch'),
            capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Verify source web/worker/schedulers are stopped',result.stderr)

    @unittest.skipIf(socket.gethostname().split('.')[0]=='a1347-m','Only run off-target guard on another host')
    def test_other_hosts_cannot_restore_production(self):
        result = subprocess.run(['node',str(SCRIPT),'/missing/app','/missing/dump','/missing/output',
                                 '--source-writers-stopped'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('only on a1347-m',result.stderr)


if __name__ == '__main__':
    unittest.main()
