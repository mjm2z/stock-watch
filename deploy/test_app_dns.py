import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('dns_switch', Path(__file__).with_name('switch-app-dns-root.py'))
dns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns)


class DNSPatchTests(unittest.TestCase):
    def test_only_app_records_change_and_patch_is_idempotent(self):
        original = ('[Service]\nExecStart=/usr/sbin/dnsmasq --no-daemon '
                    '--address=/sandbox.home.arpa/192.168.4.36 --server=1.1.1.1 '
                    '--address=/logs.home.arpa/192.168.4.36\nRestart=on-failure\n')
        updated = dns.patch(original)
        self.assertIn('--address=/sandbox.home.arpa/192.168.4.36 --server=1.1.1.1', updated)
        self.assertTrue(updated.endswith('\nRestart=on-failure\n'))
        for name in dns.NAMES:
            self.assertEqual(updated.count(f'--address=/{name}.home.arpa/192.168.4.35'), 1)
        self.assertEqual(dns.patch(updated), updated)

    def test_custom_mapping_requires_review(self):
        with self.assertRaises(ValueError):
            dns.patch('ExecStart=/usr/sbin/dnsmasq --address=/radar.home.arpa/10.0.0.1\n')


if __name__ == '__main__':
    unittest.main()
