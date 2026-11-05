import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('validation', Path(__file__).with_name('start-backup-validation.py'))
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


class ValidationTests(unittest.TestCase):
    def test_busy_and_unknown_states_refuse_start(self):
        for state in ('active', 'activating', 'deactivating', '', 'unknown'):
            with patch.object(validation, 'run', return_value=state):
                with self.assertRaises(validation.NotReady):
                    validation.ready()

    def test_pressure_defers_without_changing_thresholds(self):
        with patch.object(validation, 'run', return_value='inactive'):
            for memory, pressure in ((1000, 0), (4000000, 40)):
                with patch.object(Path, 'read_text', side_effect=[f'MemAvailable: {memory} kB', f'full avg60={pressure}']):
                    with self.assertRaises(validation.NotReady):
                        validation.ready()
            with patch.object(Path, 'read_text', side_effect=['MemAvailable: 4000000 kB', 'full avg60=1']):
                validation.ready()


if __name__ == '__main__':
    unittest.main()
