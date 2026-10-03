import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('stockwatch_domain',Path(__file__).with_name('activate-stockwatch-domain.py'))
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class DomainTests(unittest.TestCase):
    def test_preserves_routes_and_idempotence(self):
        site='http {\n server { server_name ops.home.arpa; }\n}\n'
        dns='ExecStart=dnsmasq --address=/stockwatch.home.arpa/192.168.4.35 --address=/jobwatch.home.arpa/192.168.4.36\n'
        updated,record=module.render(site,dns)
        self.assertIn('server_name ops.home.arpa;',updated)
        self.assertIn('proxy_buffering off;',updated)
        self.assertIn('listen 3001;',updated)
        self.assertIn('--address=/jobwatch.home.arpa/192.168.4.36',record)
        self.assertEqual(module.render(updated,record),(updated,record))
    def test_rejects_unexpected_route(self):
        with self.assertRaises(SystemExit): module.render('http {server_name ops.home.arpa; server_name stockwatch.home.arpa;\n}\n','')
