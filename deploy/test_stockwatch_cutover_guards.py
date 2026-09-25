from datetime import datetime
import importlib.util
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

spec=importlib.util.spec_from_file_location('final_export',Path(__file__).with_name('final-stockwatch-export-root.py'))
exporter=importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class CutoverGuards(unittest.TestCase):
    def test_market_boundary_and_weekend(self):
        zone=ZoneInfo('America/New_York')
        for value,allowed in [('2026-09-25T09:29:00',True),('2026-09-25T09:30:00',False),
                              ('2026-09-25T15:59:00',False),('2026-09-25T16:00:00',True),
                              ('2026-09-26T12:00:00',True)]:
            self.assertEqual(exporter.outside_market(datetime.fromisoformat(value).replace(tzinfo=zone)),allowed)

    def test_waits_for_oneshot_control_process_and_stopping_jobs(self):
        self.assertTrue(exporter.busy(dict(ActiveState='activating',MainPID='0',ControlPID='321')))
        self.assertTrue(exporter.busy(dict(ActiveState='deactivating',MainPID='0',ControlPID='0')))
        self.assertTrue(exporter.busy(dict(ActiveState='active',MainPID='321',ControlPID='0')))
        self.assertFalse(exporter.busy(dict(ActiveState='active',SubState='exited',MainPID='0',ControlPID='0')))
        self.assertFalse(exporter.busy(dict(ActiveState='inactive',MainPID='0',ControlPID='0')))


if __name__=='__main__': unittest.main()
