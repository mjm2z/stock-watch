import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('activate',Path(__file__).with_name('activate-stockwatch-root.py'))
activate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(activate)


class Activation(unittest.TestCase):
    def test_enables_only_original_enabled_web_and_timers(self):
        units={'stock-watch-web.service':{'enabled':'enabled'},
               'stock-watch-worker.timer':{'enabled':'enabled'},
               'stock-watch-worker.service':{'enabled':'static'},
               'stock-watch-other.timer':{'enabled':'disabled'}}
        self.assertEqual(set(activate.enabled_sets(units)),{'stock-watch-web.service','stock-watch-worker.timer'})
        units['stock-watch-unreviewed.service']={'enabled':'enabled'}
        with self.assertRaises(RuntimeError): activate.enabled_sets(units)


if __name__=='__main__': unittest.main()
