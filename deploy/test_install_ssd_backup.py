import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('installer',Path(__file__).with_name('install-ssd-backup.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class InstallerTests(unittest.TestCase):
    def test_unknown_or_busy_services_defer(self):
        for state in ('active','activating','deactivating','','unknown'):
            with patch.object(m,'run',return_value=state):self.assertFalse(m.ready()[0])

    def test_pressure_and_memory_gate(self):
        with patch.object(m,'run',return_value='inactive'):
            for memory,pressure,expected in ((1000,0,False),(4000000,20,False),(4000000,1,True)):
                with patch.object(Path,'read_text',side_effect=[f'MemAvailable: {memory} kB',f'full avg60={pressure}']):
                    self.assertEqual(m.ready()[0],expected)

    def test_rollback_refuses_later_edit_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);a=root/'first';b=root/'later';a.write_text('installed');b.write_text('user edit')
            entries=[dict(path=str(p),installed=m.hashlib.sha256(b'installed').hexdigest(),previous=None) for p in (a,b)]
            (root/'rollback.json').write_text(json.dumps(entries))
            with patch.object(m,'run',return_value='inactive'),self.assertRaisesRegex(RuntimeError,'Subsequent edit'):
                m.rollback(root)
            self.assertEqual(a.read_text(),'installed');self.assertEqual(b.read_text(),'user edit')

    def test_rollback_removes_only_recorded_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'config';config.mkdir();new=config/'new';new.write_text('installed')
            outside=root/'unrelated';outside.write_text('keep')
            (root/'rollback.json').write_text(json.dumps([dict(path=str(new),installed=m.digest(new),previous=None)]))
            with patch.object(m,'run',return_value='inactive'),patch.object(m,'CONFIG',config):m.rollback(root)
            self.assertFalse(new.exists());self.assertEqual(outside.read_text(),'keep')

    def test_rollback_refuses_active_backup(self):
        with patch.object(m,'run',return_value='activating'),self.assertRaisesRegex(RuntimeError,'active'):
            m.rollback(Path('/does-not-exist'))


if __name__=='__main__':unittest.main()
