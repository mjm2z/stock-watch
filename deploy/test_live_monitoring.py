import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('monitoring', Path(__file__).with_name('register-live-monitoring.py'))
monitoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitoring)


class MonitoringRegistration(unittest.TestCase):
    def run_registration(self, home, replies, components):
        def response(url, timeout):
            body = io.StringIO(json.dumps(replies[url.rsplit('/', 1)[1]]))
            body.status = 200
            return body
        with patch.object(Path, 'home', return_value=home), patch.object(monitoring.socket, 'gethostname', return_value='a1347-m'), patch.object(monitoring, 'urlopen', side_effect=response), patch('sys.argv', ['register', '--components', *components]):
            monitoring.main()

    def test_independent_ready_components_preserve_config_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.config/home-ops/server.json'
            config.parent.mkdir(parents=True)
            original = {'private_setting': 'fixture-only', 'sites': [{'id': 'existing', 'url': 'http://example.test'}]}
            config.write_text(json.dumps(original))
            replies = {'market-feed': {'fresh': True, 'retention': {'healthy': True}}, 'execution': {'healthy': True, 'manual': {'configured': False}}}
            self.run_registration(home, replies, ['market-feed', 'execution'])
            actual = json.loads(config.read_text())
            self.assertEqual(actual['private_setting'], original['private_setting'])
            self.assertEqual(actual['sites'][0], original['sites'][0])
            self.assertEqual([s['id'] for s in actual['sites']], ['existing', 'stock-watch-market-feed', 'stock-watch-execution'])
            backups = list(config.parent.glob('*.before-live-paper-*'))
            self.assertEqual(json.loads(backups[0].read_text()), original)
            before = config.read_bytes()
            self.run_registration(home, replies, ['execution'])
            self.assertEqual(config.read_bytes(), before)
            self.assertEqual(len(list(config.parent.glob('*.before-live-paper-*'))), 1)

    def test_unhealthy_body_does_not_partially_register(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.config/home-ops/server.json'
            config.parent.mkdir(parents=True)
            config.write_text('{"sites":[]}')
            for replies in [
                {'market-feed': {'fresh': True, 'retention': {'healthy': False}}},
                {'market-feed': {'fresh': True, 'retention': {'healthy': True}}, 'notifications': {'healthy': False}},
            ]:
                with self.assertRaisesRegex(RuntimeError, 'not ready'):
                    self.run_registration(home, replies, list(replies))
                self.assertEqual(config.read_text(), '{"sites":[]}')
                self.assertEqual(list(config.parent.glob('*.before-live-paper-*')), [])


if __name__ == '__main__':
    unittest.main()
