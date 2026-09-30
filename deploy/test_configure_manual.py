import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('configure', Path(__file__).with_name('configure-manual-paper.py'))
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class ManualProvisioning(unittest.TestCase):
    def test_environment_edit_preserves_unrelated_secrets_and_supports_quotes(self):
        original = '# retained comment\nALPACA_API_KEY_ID="fixture-key"\nSYSTEMS_OPERATOR_TOKEN=fixture-operator\nSTOCK_WATCH_AUTOBOT_TOKEN=\n'
        updated = configure.update_env(original, {'STOCK_WATCH_AUTOBOT_TOKEN': 'a' * 40})
        self.assertIn('ALPACA_API_KEY_ID="fixture-key"', updated)
        self.assertIn('SYSTEMS_OPERATOR_TOKEN=fixture-operator', updated)
        self.assertEqual(configure.read_env(updated)['STOCK_WATCH_AUTOBOT_TOKEN'], 'a' * 40)
        with self.assertRaises(configure.ConfigurationError):
            configure.read_env('MANUAL_ALPACA_API_KEY_ID=a\nMANUAL_ALPACA_API_KEY_ID=b')
        with self.assertRaises(configure.ConfigurationError):
            configure.update_env(original, {'STOCK_WATCH_AUTOBOT_TOKEN': 'a\nEXTRA=bad'})

    def test_account_isolation_and_fresh_empty_cash_required(self):
        manual = {'id': 'manual', 'cash': '1000000', 'status': 'ACTIVE'}
        stocks, bitcoin = {'id': 'stocks'}, {'id': 'bitcoin'}
        configure.validate_accounts(manual, stocks, bitcoin, [], [])
        for bad, other, positions, orders in [
            ({**manual, 'id': 'stocks'}, bitcoin, [], []),
            (manual, stocks, [], []),
            ({**manual, 'cash': 'NaN'}, bitcoin, [], []),
            ({**manual, 'cash': '100000'}, bitcoin, [], []),
            (manual, bitcoin, [{'symbol': 'SPY'}], []),
            (manual, bitcoin, [], [{'id': 'open'}]),
            ({**manual, 'trading_blocked': True}, bitcoin, [], []),
        ]:
            with self.assertRaises(configure.ConfigurationError):
                configure.validate_accounts(bad, stocks, other, positions, orders)

    def test_matching_tokens_preserved_and_conflicts_rejected(self):
        token = 'a' * 48
        self.assertEqual(configure.select_token(token, token), token)
        self.assertGreaterEqual(len(configure.select_token()), 32)
        for existing in [('short',), (token, 'b' * 48)]:
            with self.assertRaises(configure.ConfigurationError):
                configure.select_token(*existing)

    def test_second_config_failure_restores_first_and_keeps_backups_private(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory)/'systems.env', Path(directory)/'bot.env'
            first.write_bytes(b'first-original'); second.write_bytes(b'second-original')
            updates = [(first, first.read_bytes(), b'first-new', os.getuid(), os.getgid()), (second, second.read_bytes(), b'second-new', os.getuid(), os.getgid())]
            real = configure.atomic_write
            def failing(path, content, uid, gid):
                if path == second and content == b'second-new': raise OSError('fixture failure')
                real(path, content, uid, gid)
            with patch.object(configure, 'atomic_write', side_effect=failing):
                with self.assertRaises(OSError): configure.install_configs(updates, Path(directory)/'backups')
            self.assertEqual(first.read_bytes(), b'first-original')
            self.assertEqual(second.read_bytes(), b'second-original')
            backups = [p for p in (Path(directory)/'backups').rglob('*') if p.is_file()]
            self.assertEqual(len(backups), 2)
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in backups))

    def test_concurrent_edit_is_rejected_without_backups_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'env';path.write_bytes(b'edited')
            with self.assertRaises(configure.ConfigurationError):
                configure.install_configs([(path,b'old',b'new',os.getuid(),os.getgid())], Path(directory)/'backups')
            self.assertEqual(path.read_bytes(), b'edited')
            self.assertFalse((Path(directory)/'backups').exists())


if __name__ == '__main__': unittest.main()
