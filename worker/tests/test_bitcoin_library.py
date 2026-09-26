import importlib.util
import json
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('study',Path(__file__).parents[1]/'scripts/research_bitcoin_library.py')
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)

class BitcoinLibraryTests(unittest.TestCase):
    def test_completed_bar_and_next_open_causality(self):
        chart={'status':'ready','resolution':'1Day','partial':False,'provider':'fixture','observedAt':'2026-01-03T00:00:00Z',
               'requestedEnd':'2026-01-03T00:00:00Z','bars':[
                {'at':f'2026-01-0{i}T00:00:00Z','open':100+i,'high':110,'low':90,'close':105,'volume':1} for i in (1,2,3)]}
        data=study.dataset(chart)
        self.assertEqual(len(data['bars']),2) # Third daily candle is incomplete.
        first,last=data['bars']
        self.assertEqual(first['at'],'2026-01-02T00:00:00+00:00')
        self.assertEqual(first['quote']['ask'],102)
        self.assertGreater(first['quote']['at'],first['at'])
        self.assertNotIn('quote',last)
        chart['partial']=True
        with self.assertRaises(ValueError):study.dataset(chart)

    def test_published_metrics_match_retained_runs_and_frozen_configs(self):
        root=Path(__file__).parents[2]/'lib/research'
        summary=json.loads((root/'bitcoin-study-summary.json').read_text())
        evidence=json.loads((root/'bitcoin-study-evidence.json').read_text())
        for (definition,config),s,e in zip(study.candidates(),summary['systems'],evidence['systems']):
            self.assertEqual(s['version'],config.sha256)
            self.assertEqual(s['backtest_count'],2*len(e['runs']))
            self.assertEqual(s['closed_trades'],sum(r['base']['closed_trades'] for r in e['runs']))
            for window,run in zip(s['windows'],e['runs']):
                self.assertEqual(window['net_return'],run['base']['net_return'])
                self.assertEqual(window['win_rate'],run['base']['win_rate'])
                self.assertEqual(window['stress_return'],run['double_cost']['net_return'])

if __name__=='__main__':unittest.main()
