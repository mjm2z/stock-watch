import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from stock_watch_worker.systems.execution_owner import run


class OwnerLockTests(unittest.TestCase):
    def test_legacy_tick_lock_prevents_second_execution_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.db'
            with Path(str(path)+'.systems-tick.lock').open('a') as owner:
                fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch('stock_watch_worker.systems.execution_owner.ExecutionBroker') as broker:
                    with self.assertRaises(BlockingIOError): run(path)
                    broker.assert_not_called()
            self.assertFalse(path.exists())
