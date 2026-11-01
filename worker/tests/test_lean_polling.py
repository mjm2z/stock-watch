"""Health polling must save idle SSH work without hiding stale evidence."""
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_watch_worker.lean_worker import HealthPoller, tick


class LeanPollingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        migrations = Path(__file__).resolve().parents[1] / 'migrations'
        for name in ('016_systems.sql', '027_lean_comparisons.sql'):
            self.db.executescript((migrations / name).read_text())
        self.config = {'host': 'fixture', 'expected_image': 'reviewed'}
        self.poller = HealthPoller()
        self.clock = 0.0
        clock = patch('stock_watch_worker.lean_worker.time.monotonic', side_effect=lambda: self.clock)
        observed = patch('stock_watch_worker.lean_worker.now', side_effect=lambda: f'observed-{self.clock}')
        clock.start()
        observed.start()
        self.addCleanup(clock.stop)
        self.addCleanup(observed.stop)

    def health_row(self):
        return self.db.execute('SELECT updated_at,payload_json FROM lean_runner_health').fetchone()

    def pending(self, status='lean'):
        self.db.execute("INSERT INTO lean_comparisons(id,version_id,dataset_id,status,created_at,updated_at) VALUES ('job','v','d',?,'now','now')", (status,))
        self.db.commit()

    def step(self, at):
        self.clock = at
        tick(self.db, self.folder, self.config, self.poller)

    def test_idle_checks_every_thirty_seconds_without_refreshing_cached_evidence(self):
        with patch('stock_watch_worker.lean_worker.remote', return_value={'healthy': True, 'image': 'reviewed'}) as remote:
            self.step(0)
            original = tuple(self.health_row())
            for at in (10, 20, 29):
                self.step(at)
                self.assertEqual(tuple(self.health_row()), original)
            self.assertEqual(remote.call_count, 1)
            self.step(30)
            self.assertEqual(remote.call_count, 2)
            self.assertEqual(self.health_row()['updated_at'], 'observed-30')

    def test_new_pending_work_gets_fresh_health_on_next_ten_second_tick(self):
        with patch('stock_watch_worker.lean_worker.remote', return_value={'healthy': False, 'image': 'reviewed'}) as remote:
            self.step(0)
            self.pending('queued')
            self.step(10)
            self.assertEqual(remote.call_count, 2)
            self.assertEqual(self.db.execute('SELECT status FROM lean_comparisons').fetchone()[0], 'queued')
            self.assertEqual(self.health_row()['updated_at'], 'observed-10')

    def test_active_work_keeps_health_and_status_checks_at_ten_seconds(self):
        self.pending()
        actions = []
        def response(config, message):
            actions.append(message['action'])
            return {'healthy': True, 'image': 'reviewed'} if message['action'] == 'health' else {'status': 'running'}
        with patch('stock_watch_worker.lean_worker.remote', side_effect=response):
            for at in (0, 10, 20):
                self.step(at)
            self.assertEqual(actions, ['health', 'status'] * 3)
            self.assertEqual(self.db.execute('SELECT status FROM lean_comparisons').fetchone()[0], 'lean')
            # Completing the work restores the longer interval immediately.
            self.db.execute("UPDATE lean_comparisons SET status='complete'")
            self.db.commit()
            self.step(30)
            self.assertEqual(len(actions), 6)

    def test_idle_failures_wait_thirty_seconds_and_preserve_failure_timestamp(self):
        for failure in (ConnectionError('offline'), subprocess.TimeoutExpired('ssh', 60), ValueError('invalid response')):
            with self.subTest(error=type(failure).__name__):
                self.poller = HealthPoller()
                with patch('stock_watch_worker.lean_worker.remote', side_effect=failure) as remote:
                    self.step(0)
                    for at in (10, 20, 29):
                        self.step(at)
                    self.assertEqual(remote.call_count, 1)
                    row = self.health_row()
                    self.assertEqual(row['updated_at'], 'observed-0')
                    self.assertFalse(json.loads(row['payload_json'])['healthy'])
                    self.step(30)
                    self.assertEqual(remote.call_count, 2)

    def test_slow_probe_waits_from_completion_before_retry(self):
        def slow_failure(config, message):
            self.clock += 60
            raise subprocess.TimeoutExpired('ssh', 60)
        with patch('stock_watch_worker.lean_worker.remote', side_effect=slow_failure) as remote:
            self.step(0)
            self.assertEqual(self.health_row()['updated_at'], 'observed-60')
            self.step(70)
            self.assertEqual(remote.call_count, 1)
            self.step(90)
            self.assertEqual(remote.call_count, 2)

    def test_configuration_change_invalidates_health_immediately(self):
        with patch('stock_watch_worker.lean_worker.remote', return_value={'healthy': True, 'image': 'reviewed'}) as remote:
            self.step(0)
            self.config['expected_image'] = 'new-pin'
            self.step(1)
            self.assertEqual(remote.call_count, 2)
            health = json.loads(self.health_row()['payload_json'])
            self.assertFalse(health['healthy'])
            self.assertIn('reviewed pin', health['error'])
            self.config = None
            self.step(2)
            self.assertFalse(json.loads(self.health_row()['payload_json'])['configured'])
            self.assertEqual(remote.call_count, 2)

    def test_active_status_transport_failure_does_not_fail_or_duplicate_job(self):
        self.pending()
        actions = []
        def response(config, message):
            actions.append(message['action'])
            if message['action'] == 'health':
                return {'healthy': True, 'image': 'reviewed'}
            raise ConnectionError('uncertain status')
        with patch('stock_watch_worker.lean_worker.remote', side_effect=response):
            self.step(0)
            self.step(10)
        self.assertEqual(actions, ['health', 'status'] * 2)
        self.assertEqual(self.db.execute('SELECT status FROM lean_comparisons').fetchone()[0], 'lean')


if __name__ == '__main__':
    unittest.main()
