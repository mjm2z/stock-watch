import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('lean_watchdog',Path(__file__).with_name('lean-watchdog.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class WatchdogTests(unittest.TestCase):
    def test_thresholds_gap_and_recovery(self):
        s={}
        for t in (0,60):m.advance(s,False,t)
        self.assertEqual(s['events'],[])
        m.advance(s,False,120);m.advance(s,False,180)
        self.assertEqual(len(s['events']),1)
        m.advance(s,True,240);m.advance(s,True,300)
        self.assertEqual([e['kind'] for e in s['events']],['outage','recovery'])
        s={};m.advance(s,False,0);m.advance(s,False,60);m.advance(s,False,300)
        self.assertEqual(s['events'],[])
    def test_delivery_once_and_uncertain_never_retried(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json';at=1791043200
            with patch.object(m,'probe',return_value=False):
                sender=unittest.mock.Mock(return_value={'status':'sent','message_id':123})
                for n in range(5):m.tick(p,{},sender,at+n*60)
                self.assertEqual(sender.call_count,1)
                s=json.loads(p.read_text());s['events'][0]['delivery']='sending';m.save(p,s)
                m.tick(p,{},sender,at+300)
                self.assertEqual(sender.call_count,1)
                self.assertEqual(json.loads(p.read_text())['events'][0]['delivery'],'uncertain')
    def test_quiet_hours_and_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'s.json';sender=unittest.mock.Mock()
            with patch.object(m,'probe',return_value=False):
                for n in range(3):m.tick(p,{'delivery_enabled':False},sender,1791043200+n*60)
            sender.assert_not_called()
    def test_bad_health(self):
        from unittest.mock import MagicMock
        response=MagicMock();response.__enter__.return_value=response;response.status=200
        for body in ({'healthy':True,'configured':True,'stale':True},{'healthy':False},{}):
            with patch.object(m,'urlopen',return_value=response),patch.object(m.json,'load',return_value=body):
                self.assertFalse(m.probe())
if __name__=='__main__':unittest.main()
