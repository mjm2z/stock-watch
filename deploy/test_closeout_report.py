import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('closeout', Path(__file__).with_name('closeout-report.py'))
closeout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(closeout)


class CloseoutTests(unittest.TestCase):
    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.db'
            result = closeout.capture(lambda: closeout.inspect_database(path))
            self.assertFalse(result['available'])
            self.assertFalse(path.exists())

    def test_queries_do_not_mutate_database_and_missing_evidence_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.db'
            with sqlite3.connect(path) as db:
                db.executescript("CREATE TABLE schema_migrations(version TEXT); INSERT INTO schema_migrations VALUES ('020_correctness');")
            before = path.read_bytes()
            result = closeout.inspect_database(path)
            self.assertEqual(result['schema']['result'], [{'version': '020_correctness'}])
            self.assertFalse(result['stock_reconciliation']['available'])
            self.assertEqual(path.read_bytes(), before)

    def test_blocked_worker_is_not_hidden_by_successful_http_transport(self):
        with patch.object(closeout, 'get_json', return_value=(503, {'healthy': False, 'checks': [
                {'worker': 'discovery', 'state': 'blocked', 'healthy': False, 'blocked': 6}]})):
            result = closeout.capture(closeout.readiness)
        self.assertTrue(result['available'])
        self.assertFalse(result['result']['healthy'])
        self.assertEqual(result['result']['http_status'], 503)

    def test_unregistered_local_account_does_not_claim_empty_broker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE btc_accounts(id TEXT)')
            with patch.dict(closeout.os.environ, {'BITCOIN_ALPACA_API_KEY_ID': 'private-key',
                    'BITCOIN_ALPACA_API_SECRET_KEY': 'private-secret', 'ALPACA_API_KEY_ID': 'stock-key'}), \
                    patch.object(closeout, 'get_json', side_effect=[
                        (200, {'id': 'private-account', 'currency': 'USD', 'cash': '1000'}),
                        (200, [{'symbol': 'BTCUSD'}]), (200, [{'id': 'private-order'}])]) as get:
                result = closeout.broker_observation(path, True)
            self.assertFalse(result['local_account_registered'])
            self.assertIsNone(result['account_identity_matches'])
            self.assertEqual(result['position_count'], 1)
            self.assertEqual(result['open_order_count_up_to_500'], 1)
            self.assertNotIn('private-', json.dumps(result))
            self.assertTrue(all(call.args[0].startswith('https://paper-api.alpaca.markets/v2/') for call in get.call_args_list))

    def test_error_details_are_redacted(self):
        def fail():
            raise ValueError('private-token=secret')
        self.assertEqual(closeout.capture(fail), {'available': False, 'error_type': 'ValueError'})

    def test_distinct_credentials_do_not_prove_distinct_broker_accounts(self):
        def observe(path, bitcoin, identities):
            identities[bitcoin] = 'same-private-account'
            return {'configured': True}
        with patch.object(closeout, 'broker_observation', side_effect=observe):
            result = closeout.broker_report(Path('unused'))
        self.assertFalse(result['distinct_broker_accounts'])
        self.assertNotIn('same-private-account', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
