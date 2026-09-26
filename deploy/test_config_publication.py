import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ProtectedPublication(unittest.TestCase):
    def test_config_drift_refuses_publication_and_success_retains_predecessor(self):
        script = Path(__file__).with_name('publish-protected-config.py')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live, proposed = root/'live.json', root/'proposed.json'
            old = '{"token":"preserve","endpoint":"old"}\n'
            new = '{"token":"preserve","endpoint":"new"}\n'
            live.write_text(old)
            proposed.write_text(new)
            refused = subprocess.run([sys.executable,str(script),str(proposed),str(live),'0'*64],capture_output=True)
            self.assertNotEqual(refused.returncode,0)
            self.assertEqual(live.read_text(),old)
            self.assertFalse(list(root.glob('*.before-*')))
            digest = hashlib.sha256(old.encode()).hexdigest()
            subprocess.run([sys.executable,str(script),str(proposed),str(live),digest],check=True,capture_output=True)
            self.assertEqual(live.read_text(),new)
            self.assertEqual(live.stat().st_mode & 0o777,0o600)
            self.assertEqual((root/'live.json.before-app-cutover-20260925').read_text(),old)
            self.assertEqual(json.loads(live.read_text())['token'],'preserve')


if __name__ == '__main__':
    unittest.main()
