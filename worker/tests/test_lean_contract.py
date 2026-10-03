import copy,unittest
from stock_watch_worker.lean_contract import compare,validate
class LeanContractTests(unittest.TestCase):
    def sample(self):
        return {'decisions':[{'at':'2020-01-01T00:00:00Z','action':'buy'}],'fills':[{'at':'2020-01-01T00:00:01Z','side':'buy','qty':1,'price':100,'fee':.25}],'equity_curve':[{'at':'2020-01-01T00:00:01Z','equity':299.75,'cash':200}],'ending_equity':299.75,'fees':.25,'maximum_drawdown':-.001}
    def test_exact_and_normalized_times(self):
        a=self.sample();b=copy.deepcopy(a);b['decisions'][0]['at']='2020-01-01T00:00:00+00:00'
        self.assertEqual(compare(a,b,1e-9)['outcome'],'matched')
    def test_detects_signal_fill_and_accounting_changes(self):
        a=self.sample();b=copy.deepcopy(a);b['decisions'][0]['action']='hold';b['fills'][0]['price']=110;b['ending_equity']=280
        result=compare(a,b,1e-9);self.assertEqual(result['difference_count'],3)
        self.assertEqual(result['first_divergence']['kind'],'decisions')
    def test_missing_rows_do_not_match(self):
        a=self.sample();b=copy.deepcopy(a);b['fills']=[]
        self.assertEqual(compare(a,b,1e-9)['outcome'],'differences')
    def test_non_finite_fails_closed(self):
        a=self.sample();b=copy.deepcopy(a);b['fees']=float('nan')
        with self.assertRaises(ValueError):compare(a,b,1e-9)
    def test_rejects_unsupported_config(self):
        with self.assertRaises(ValueError):validate({'asset':'stocks'}, {})
