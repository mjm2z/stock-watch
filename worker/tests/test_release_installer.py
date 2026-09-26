import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('reviewed_installer',Path(__file__).resolve().parents[2]/'deploy/install-reviewed-release.py')
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

class InstallerDrainTests(unittest.TestCase):
    def test_supervised_installer_does_not_wait_on_itself(self):
        lines=['stock-watch-release-example.service transient -',
               'stock-watch-web.service enabled enabled',
               'stock-watch-worker.service static -',
               'stock-watch-worker.timer enabled enabled']
        with patch.object(installer,'output',side_effect=['4242','5000']):
            self.assertEqual(installer.drain_services(lines,4242),['stock-watch-worker.service'])
    def test_other_running_services_are_not_exempted_by_name(self):
        lines=['stock-watch-release-other.service transient -',
               'stock-watch-discovery.service static -']
        with patch.object(installer,'output',side_effect=['6000','0']):
            self.assertEqual(installer.drain_services(lines,4242),[
                'stock-watch-release-other.service','stock-watch-discovery.service'])

if __name__=='__main__':unittest.main()
