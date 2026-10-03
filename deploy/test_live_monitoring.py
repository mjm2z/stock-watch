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
            self.assertEqual(actual['sites'][1]['kind'], 'API')
            self.assertEqual(actual['sites'][1]['parent_site'], 'stock-watch')
            self.assertNotIn('page_url', actual['sites'][1])
            backups = list(config.parent.glob('*.before-live-paper-*'))
            self.assertEqual(json.loads(backups[0].read_text()), original)
            before = config.read_bytes()
            self.run_registration(home, replies, ['execution'])
            self.assertEqual(config.read_bytes(), before)
            self.assertEqual(len(list(config.parent.glob('*.before-live-paper-*'))), 1)

    def test_proxy_uses_compatibility_listener_and_canonical_browser_link(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.config/home-ops/server.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'sites': [{'id': 'stock-watch', 'url': 'http://192.168.4.35:3001', 'open_url': 'http://stockwatch.home.arpa:3001'}]}))
            self.run_registration(home, {'market-feed': {'fresh': True, 'retention': {'healthy': True}}}, ['proxy'])
            sites = json.loads(config.read_text())['sites']
            self.assertEqual(sites[0]['url'], 'http://192.168.4.35:3001')
            self.assertEqual(sites[0]['open_url'], 'http://stockwatch.home.arpa/')
            self.assertEqual(sites[1]['url'], 'http://192.168.4.36:3001/api/health/market-feed')
            self.assertEqual(sites[1]['machine'], 'a1990')

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

    def test_previous_json_as_website_registration_is_corrected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.config/home-ops/server.json'
            config.parent.mkdir(parents=True)
            url = 'http://192.168.4.35:3001/api/health/execution'
            config.write_text(json.dumps({'sites': [{'id': 'stock-watch-execution', 'url': url, 'page_url': url, 'kind': 'Website', 'extra': 'preserved'}]}))
            self.run_registration(home, {'execution': {'healthy': True}}, ['execution'])
            site = json.loads(config.read_text())['sites'][0]
            self.assertEqual(site['kind'], 'API')
            self.assertNotIn('page_url', site)
            self.assertEqual(site['extra'], 'preserved')


if __name__ == '__main__':
    unittest.main()
