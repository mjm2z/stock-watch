import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch
from stock_watch_worker.database import connect,apply_migrations
from stock_watch_worker.systems.discovery import summarize,PROFILES,templates,schedule,run
from stock_watch_worker.systems.reporting import trade_metrics
from stock_watch_worker.systems.automatic_paper import prepare,eligible
from stock_watch_worker.systems.coordinator import reserve
from stock_watch_worker.systems.research import register_version
from stock_watch_worker.systems.engine import canonical
NOW=datetime(2026,9,26,12,tzinfo=timezone.utc)

class MetricsTests(unittest.TestCase):
    def test_cash_profit_includes_buy_and_sell_fees_and_partial_exits(self):
        r={'starting_cash':200,'ending_equity':209,'fills':[
            {'at':'a','symbol':'BTC/USD','side':'buy','qty':1,'price':100,'fee':1},
            {'at':'b','symbol':'BTC/USD','side':'sell','qty':.49,'price':110,'fee':.5},
            {'at':'c','symbol':'BTC/USD','side':'sell','qty':.5,'price':120,'fee':.6}]}
        m=trade_metrics(r,'bitcoin')
        self.assertTrue(m['available']);self.assertEqual(m['closed_trades'],1)
        self.assertAlmostEqual(m['realized_closed_pnl'],12.8)
        self.assertEqual(m['net_pnl'],9)
        self.assertAlmostEqual(m['open_and_partial_pnl'],-3.8)
    def test_same_entry_with_different_exits_is_one_unique_trade(self):
        report={'starting_cash':200,'ending_equity':201,'fills':[
            {'at':'entry','symbol':'BTC/USD','side':'buy','qty':1,'price':100,'fee':0},
            {'at':'exit1','symbol':'BTC/USD','side':'sell','qty':1,'price':101,'fee':0}]}
        first=trade_metrics(report,'bitcoin')['trades'][0]['id']
        report['fills'][-1]['at']='exit2'
        self.assertEqual(first,trade_metrics(report,'bitcoin')['trades'][0]['id'])
    def test_missing_or_sampled_evidence_is_not_zero(self):
        self.assertFalse(trade_metrics({},'bitcoin')['available'])
        self.assertFalse(trade_metrics({'fills':[],'fills_in_full_artifact':120,'starting_cash':300,'ending_equity':300},'bitcoin')['available'])

class QualificationTests(unittest.TestCase):
    def rows(self,passing=100):
        rows=[]
        for i in range(20):
            for j,p in enumerate(PROFILES):
                start=NOW-timedelta(days=2000-100*i);end=start+timedelta(days=90)
                result={'valid':True,'net_return':.1 if i*5+j<passing else -.01,'drawdown':.05,
                        'trades':[{'id':f'{i}-{n}','pnl':1} for n in range(2)]}
                rows.append({'profile':p,'starts_at':start.isoformat(),'ends_at':end.isoformat(),'result_json':canonical(result)})
        return rows
    def test_80_is_boundary_and_79_fails(self):
        self.assertTrue(summarize(self.rows(80),.8)['passed'])
        self.assertFalse(summarize(self.rows(79),.8)['passed'])
        self.assertFalse(summarize(self.rows(80),.85)['passed'])
    def test_repeated_trades_and_invalid_coverage_do_not_qualify(self):
        rows=self.rows()
        for r in rows:
            v=json.loads(r['result_json']);v['trades']=[{'id':'same','pnl':1}];r['result_json']=canonical(v)
        self.assertFalse(summarize(rows,.8)['passed'])
        rows=self.rows();v=json.loads(rows[0]['result_json']);v['valid']=False;rows[0]['result_json']=canonical(v)
        self.assertFalse(summarize(rows,.8)['passed'])
    def test_one_excessive_drawdown_disqualifies(self):
        rows=self.rows();v=json.loads(rows[0]['result_json']);v['drawdown']=.10001;rows[0]['result_json']=canonical(v)
        self.assertFalse(summarize(rows,.8)['passed'])

class AutomaticPaperTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=connect(Path(self.temp.name)/'db');apply_migrations(self.db)
        self.version=register_version(self.db,next(templates('bitcoin'))[1])
        with self.db:
            self.db.execute("INSERT INTO discovery_batches(id,created_at,updated_at) VALUES ('batch',?,?)",(NOW.isoformat(),NOW.isoformat()))
            self.db.execute("INSERT INTO discovery_trials(id,batch_id,version_id,asset,policy_id,budget,status,created_at,finished_at,expires_at,result_json) VALUES ('trial','batch',?,'bitcoin',1,'200','completed',?,?,?,?)",
                (self.version,NOW.isoformat(),NOW.isoformat(),(NOW+timedelta(days=8)).isoformat(),canonical({'passed':True,'scenario_count':100,'scenario_pass_rate':.8})))
            self.db.execute("INSERT INTO btc_health VALUES ('data',?,NULL)",(NOW.isoformat(),))
        self.broker=Mock();self.broker.account.return_value={'id':'paper','cash':'1000'}
        self.broker.positions.return_value=[];self.broker.open_orders.return_value=[]
        self.broker.fees.return_value=[];self.broker.fills.return_value=[]
    def tearDown(self):
        self.db.close();self.temp.cleanup()
    def prepare(self):
        with patch('stock_watch_worker.systems.coordinator.reconcile',return_value=True):prepare(self.db,self.broker,NOW)
    def test_authorization_without_forward_gate_is_idempotent_and_does_not_order(self):
        self.prepare();self.prepare()
        self.assertEqual(eligible(self.db,self.version,NOW),'trial')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM btc_allocations').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT cash FROM btc_accounts').fetchone()[0],'800')
        self.assertFalse(self.broker.submit.called)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM btc_forward').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'cap'):
            reserve(self.db,self.version,'buy',1,100,NOW,'trial','over cap')
        order=reserve(self.db,self.version,'buy',.4,100,NOW,'trial','signal')
        self.assertTrue(order.startswith('btc2-'))
        with self.assertRaisesRegex(ValueError,'outstanding'):
            reserve(self.db,self.version,'buy',.4,100,NOW,'trial','duplicate')
    def test_new_failed_evaluation_suspends_old_automatic_authority(self):
        self.prepare()
        with self.db:self.db.execute("INSERT INTO discovery_trials(id,batch_id,version_id,asset,policy_id,budget,status,created_at,finished_at,expires_at,result_json) VALUES ('new-trial','batch',?,'bitcoin',1,'200','completed',?,?,?,?)",
            (self.version,NOW.isoformat(),(NOW+timedelta(seconds=1)).isoformat(),(NOW+timedelta(days=8)).isoformat(),canonical({'passed':False,'scenario_count':100,'scenario_pass_rate':.79})))
        self.assertIsNone(eligible(self.db,self.version,NOW+timedelta(seconds=2)))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM btc_allocations').fetchone()[0],1)
    def test_policy_pause_expiry_and_budget_change_block_entries(self):
        self.prepare()
        with self.db:self.db.execute('UPDATE research_policies SET enabled=0')
        self.assertIsNone(eligible(self.db,self.version,NOW))
        with self.db:self.db.execute('UPDATE research_policies SET enabled=1')
        self.assertIsNone(eligible(self.db,self.version,NOW+timedelta(days=9)))
        with self.db:self.db.execute("UPDATE btc_allocations SET budget='199'")
        self.assertIsNone(eligible(self.db,self.version,NOW))
    def test_failed_threshold_no_capital_and_broker_account_never_reset(self):
        with self.db:self.db.execute("UPDATE discovery_trials SET result_json=?",(canonical({'passed':False,'scenario_count':100,'scenario_pass_rate':.79}),))
        self.prepare()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM btc_allocations').fetchone()[0],0)
        self.broker.reset.assert_not_called()
    def test_existing_manual_allocation_is_not_taken_over(self):
        with self.db:
            self.db.execute("INSERT INTO btc_accounts(id,created_at) VALUES ('paper',?)",(NOW.isoformat(),))
            self.db.execute("INSERT INTO btc_allocations(version_id,account_id,budget,cash,high_water,approved_at) VALUES (?,'paper','100','100','100',?)",(self.version,NOW.isoformat()))
        self.prepare()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_authorizations').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT budget FROM btc_allocations').fetchone()[0],'100')
    def test_schedule_is_idempotent_and_bounded(self):
        with patch('stock_watch_worker.systems.discovery.proposals'):
            batch=schedule(self.db,NOW);schedule(self.db,NOW)
        self.assertEqual(batch,'2026-09-26')
        self.assertLessEqual(self.db.execute('SELECT COUNT(*) FROM discovery_trials').fetchone()[0],13)
        with patch('stock_watch_worker.systems.discovery.scenario') as replay:
            run(self.db,Path(self.temp.name)/'db',seconds=0,now=NOW)
            replay.assert_not_called()

if __name__=='__main__':unittest.main()
