from __future__ import annotations
import json
import unittest
from datetime import datetime, timezone, timedelta
from dataclasses import replace
from stock_watch_worker.strategy import sizing_from_config, calculate_notional
from stock_watch_worker.domain import RiskLevel
from stock_watch_worker.assessment import review_inputs, persist_assessments
from stock_watch_worker.features import build_feature_set
from stock_watch_worker.entry_controls import check_entry
from stock_watch_worker.paper_orders import create_order_intent, submit_or_reconcile_order
import test_scan_executor as scan_tests
from test_scan_executor import NOW
import test_paper_orders as order_tests
from test_paper_orders import FakeBroker

class SizingConfigurationTests(unittest.TestCase):
    def test_configured_bands_and_multiplier_are_used(self):
        policy=sizing_from_config({'sizing':{'bands':[{'minimum_score':75,'notional_usd':5}], 'medium_risk_multiplier':1}})
        self.assertEqual(calculate_notional(94,RiskLevel.MEDIUM,policy=policy),5)
    def test_nonfinite_and_duplicate_bands_rejected(self):
        for value in [float('nan'),float('inf'),True,-1]:
            with self.assertRaises(ValueError):sizing_from_config({'sizing':{'medium_risk_multiplier':value}})
        with self.assertRaises(ValueError):sizing_from_config({'sizing':{'bands':[{'minimum_score':75,'notional_usd':10}]*2}})

class AssessmentControlTests(unittest.TestCase):
    def setUp(self):
        self.case=scan_tests.ScanExecutorTests();self.case.setUp();self.case._seed('development')
        self.db=self.case.connection;self.inputs=self.case._complete_inputs()
    def tearDown(self):self.case.tearDown()
    def test_actual_metrics_and_anomalies_are_distinct_from_pillar_coverage(self):
        candidate=self.inputs.candidates[0]
        features=build_feature_set(as_of=self.inputs.data_cutoff,bars=candidate.bars,spy_bars=self.inputs.spy_bars,fundamentals=candidate.fundamentals)
        spike=replace(candidate.bars[-1],open=candidate.bars[-1].open*3,high=candidate.bars[-1].high*3,low=candidate.bars[-1].low*3,close=candidate.bars[-1].close*3)
        result=review_inputs(replace(candidate,bars=candidate.bars[:-1]+(spike,)),features,self.inputs.data_cutoff,self.inputs.spy_bars)
        self.assertIn('price_jump_requires_verification',result['blockers'])
        self.assertEqual(result['pillars']['valuation']['expected'],2)
    def test_shadow_assessments_are_idempotent_and_cannot_create_orders(self):
        from stock_watch_worker.scan_executor import execute_scan
        execute_scan(self.db,inputs=self.inputs,now=NOW)
        execute_scan(self.db,inputs=self.inputs,now=NOW)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM shadow_assessments').fetchone()[0],12)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM paper_orders').fetchone()[0],0)
        weights=[json.loads(row[0])['weights'] for row in self.db.execute("SELECT config_json FROM shadow_assessments WHERE variant='horizon-weights-v1'")]
        self.assertEqual(len({json.dumps(v,sort_keys=True) for v in weights}),4)

    def test_scan_allocates_to_highest_score_before_alphabetical_order(self):
        from stock_watch_worker.scan_executor import execute_scan
        self.db.execute("UPDATE strategy_versions SET status='paper'")
        self.db.execute("INSERT INTO instruments(id,symbol,active,fractionable) VALUES (3,'ZZZ',1,1)")
        self.db.execute("INSERT INTO universe_memberships VALUES (1,3)")
        account=self.db.execute("INSERT INTO broker_account_snapshots(captured_at,broker,account_id,status,currency,cash,equity,long_market_value,trading_blocked,account_blocked,trade_suspended,raw_json) VALUES ('2026-08-20T20:16:00Z','alpaca-paper','fixture','ACTIVE','USD',1000,1000,0,0,0,0,'{}')").lastrowid
        self.db.execute("INSERT INTO broker_reconciliations(captured_at,account_snapshot_id,status,expected_positions_json,actual_positions_json,discrepancies_json,corporate_actions_json) VALUES ('2026-08-20T20:16:00Z',?,'matched','{}','{}','[]','[]')",(account,))
        original=self.inputs.candidates[0]
        higher=replace(original,instrument_id=3,symbol='ZZZ',fundamentals=replace(original.fundamentals,revenue_growth=.3,net_margin=.25,free_cash_flow_margin=.2,liabilities_to_equity=0,price_to_earnings=10,free_cash_flow_yield=.08))
        execute_scan(self.db,inputs=replace(self.inputs,candidates=(original,higher)),now=NOW)
        first=self.db.execute('SELECT s.instrument_id FROM paper_orders o JOIN signals s ON s.id=o.signal_id ORDER BY o.rowid LIMIT 1').fetchone()
        self.assertEqual(first[0],3)

class EntryControlTests(unittest.TestCase):
    def setUp(self):
        self.case=order_tests.PaperOrderTests();self.case.setUp();self.db=self.case.connection
        self.now=datetime(2026,8,20,14,tzinfo=timezone.utc)
        self.order=create_order_intent(self.db,signal_id='signal-5',notional_usd=10).order_id
        self.db.execute("UPDATE strategy_versions SET config_json=?",(json.dumps({'entry_policy':{'enabled':True}}),))
        self.db.execute("UPDATE signals SET as_of='2026-08-20T13:45:00Z'")
        self.db.execute("UPDATE feature_snapshots SET features_json=?",(json.dumps({'raw':{'reference_close':100}}),))
        self.context={'clock':{'timestamp':self.now.isoformat(),'is_open':True,'next_open':'2026-08-21T13:30:00Z'},'account':{'status':'ACTIVE','cash':'1000','buying_power':'1000','trading_blocked':False,'account_blocked':False},'quote':{'t':self.now.isoformat(),'bp':100,'ap':100.1}}
        self.broker=FakeBroker();self.broker.get_entry_context=lambda symbol:self.context
    def tearDown(self):self.case.tearDown()
    def test_fresh_quote_and_cash_allow_order(self):
        result=submit_or_reconcile_order(self.db,order_id=self.order,broker=self.broker,now=self.now)
        self.assertEqual(self.broker.submit_calls,1);self.assertEqual(result.status,'accepted')
    def test_wide_spread_defers_without_submission(self):
        self.context['quote']['ap']=103
        result=submit_or_reconcile_order(self.db,order_id=self.order,broker=self.broker,now=self.now)
        self.assertEqual(result.status,'pending');self.assertEqual(self.broker.submit_calls,0)
        self.assertEqual(self.db.execute('SELECT reason FROM entry_checks').fetchone()[0],'spread_too_wide')
    def test_closed_market_waits_for_next_session(self):
        self.context['clock']['is_open']=False
        result=submit_or_reconcile_order(self.db,order_id=self.order,broker=self.broker,now=self.now)
        self.assertEqual(result.status,'pending');self.assertEqual(self.broker.submit_calls,0)
        self.assertEqual(self.db.execute('SELECT next_check_at FROM deferred_entries').fetchone()[0],'2026-08-21T13:45:00Z')
    def test_moved_price_releases_reserved_capital(self):
        self.context['quote'].update(bp=110,ap=110.1)
        submit_or_reconcile_order(self.db,order_id=self.order,broker=self.broker,now=self.now)
        self.assertEqual(self.broker.submit_calls,0)
        self.assertEqual(self.db.execute('SELECT status FROM paper_trade_lots').fetchone()[0],'canceled')
    def test_expired_signal_does_not_submit(self):
        self.context['clock']['timestamp']=(self.now+timedelta(hours=2)).isoformat()
        result=submit_or_reconcile_order(self.db,order_id=self.order,broker=self.broker,now=self.now+timedelta(hours=2))
        self.assertEqual(result.status,'rejected');self.assertEqual(self.broker.submit_calls,0)
    def test_existing_broker_order_is_reconciled_even_if_local_signal_is_old(self):
        self.broker.existing={'id':'broker-1','status':'new'}
        result=submit_or_reconcile_order(self.db,order_id=self.order,broker=self.broker,now=self.now+timedelta(days=1))
        self.assertEqual(result.status,'accepted');self.assertEqual(self.broker.submit_calls,0)
    def test_provider_failure_cannot_allow_an_order(self):
        self.broker.get_entry_context=lambda symbol:(_ for _ in ()).throw(TimeoutError())
        result=submit_or_reconcile_order(self.db,order_id=self.order,broker=self.broker,now=self.now)
        self.assertEqual(result.status,'pending');self.assertEqual(self.broker.submit_calls,0)

    def test_stale_quote_and_blocked_account_prevent_submission(self):
        self.context['quote']['t']=(self.now-timedelta(minutes=3)).isoformat()
        self.assertEqual(check_entry(self.db,self.order,self.broker,self.now),('defer','stale_quote'))
        self.db.execute('DELETE FROM deferred_entries')
        self.context['account']['trading_blocked']=True
        self.assertEqual(check_entry(self.db,self.order,self.broker,self.now),('reject','broker_account_blocked'))
    def test_low_cash_and_verified_earnings_block_entry(self):
        self.context['account']['cash']='9'
        self.assertEqual(check_entry(self.db,self.order,self.broker,self.now),('reject','insufficient_unreserved_cash'))
    def test_verified_earnings_window_blocks_entry(self):
        self.db.execute('INSERT INTO instrument_context VALUES (1,?,?,?,?)',('Information Technology',self.now.isoformat(),self.now.isoformat(),'fixture'))
        self.assertEqual(check_entry(self.db,self.order,self.broker,self.now),('reject','earnings_window'))
    def test_maintenance_cannot_submit_before_scheduled_next_open_check(self):
        self.context['clock']['is_open']=False
        check_entry(self.db,self.order,self.broker,self.now)
        next_open=datetime(2026,8,21,13,30,tzinfo=timezone.utc)
        self.context['clock'].update(is_open=True,timestamp=next_open.isoformat())
        self.context['quote']['t']=next_open.isoformat()
        result=submit_or_reconcile_order(self.db,order_id=self.order,broker=self.broker,now=next_open)
        self.assertEqual(self.broker.submit_calls,0);self.assertEqual(result.status,'pending')
    def test_expiry_releases_capacity_even_during_quote_provider_outage(self):
        self.context['clock']['is_open']=False
        check_entry(self.db,self.order,self.broker,self.now)
        self.broker.get_entry_context=lambda symbol:(_ for _ in ()).throw(TimeoutError())
        later=datetime(2026,8,21,14,1,tzinfo=timezone.utc)
        self.assertEqual(check_entry(self.db,self.order,self.broker,later),('reject','signal_expired'))

    def test_future_entries_do_not_poll_broker_overnight(self):
        from stock_watch_worker.entry_controls import prepare_due_entries
        self.context['clock']['is_open']=False
        check_entry(self.db,self.order,self.broker,self.now)
        self.assertFalse(prepare_due_entries(self.db,object(),self.now+timedelta(minutes=1)))
    def test_existing_fills_are_reconciled_before_position_snapshot(self):
        from stock_watch_worker.entry_controls import prepare_due_entries
        from unittest.mock import patch
        older=create_order_intent(self.db,signal_id='signal-21',notional_usd=10)
        # The fixture's new policy requires a review before reserving another order.
        if older.order_id is None:
            self.db.execute("INSERT INTO assessment_reviews VALUES ('signal-21','2026-08-20','{\"blockers\":[]}','fixture')")
            older=create_order_intent(self.db,signal_id='signal-21',notional_usd=10)
        self.db.execute("UPDATE paper_orders SET status='accepted' WHERE id=?",(older.order_id,))
        events=[]
        with patch('stock_watch_worker.paper_orders.submit_or_reconcile_order',side_effect=lambda *a,**kw:events.append('fill')),patch('stock_watch_worker.broker_reconciliation.capture_and_reconcile_broker',side_effect=lambda *a,**kw:events.append('positions')):
            self.assertTrue(prepare_due_entries(self.db,self.broker,self.now))
        self.assertEqual(events,['fill','positions'])

class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.case=order_tests.PaperOrderTests();self.case.setUp();self.db=self.case.connection
        self.db.execute("UPDATE strategy_versions SET config_json=?",(json.dumps({'entry_policy':{'enabled':True},'portfolio':{'maximum_notional_usd':300,'maximum_sector_notional_usd':60}}),))
        for row in self.db.execute('SELECT id FROM signals').fetchall():
            self.db.execute('INSERT INTO assessment_reviews VALUES (?,?,?,?)',(row[0],'2026-08-20',json.dumps({'blockers':[]}), 'test'))
        self.db.commit()
    def tearDown(self):self.case.tearDown()
    def add_signal(self, number, sector=None):
        self.db.execute("INSERT INTO instruments(id,symbol,active,fractionable) VALUES (?,?,1,1)",(number,f'T{number}'))
        self.db.execute("""INSERT INTO signals(id,scan_run_id,strategy_version_id,instrument_id,feature_snapshot_id,horizon_trading_days,as_of,opportunity_score,data_completeness,risk_level,decision,explanation)
            SELECT ?,scan_run_id,strategy_version_id,?,feature_snapshot_id,horizon_trading_days,as_of,opportunity_score,data_completeness,risk_level,decision,explanation FROM signals WHERE id='signal-5'""",(f'signal-{number}-new',number))
        self.db.execute("INSERT INTO assessment_reviews VALUES (?,'2026-08-20','{\"blockers\":[]}','test')",(f'signal-{number}-new',))
        if sector:self.db.execute("INSERT INTO instrument_context VALUES (?,?,NULL,'2026-08-20','fixture')",(number,sector))
        self.db.commit()
        return f'signal-{number}-new'
    def test_sector_cap_counts_pending_reservations(self):
        for number in range(2,6):
            self.assertEqual(create_order_intent(self.db,signal_id=self.add_signal(number,'Energy'),notional_usd=15).action,'created')
        result=create_order_intent(self.db,signal_id=self.add_signal(6,'Energy'),notional_usd=5)
        self.assertEqual(result.reason,'sector_notional_limit')
    def test_unknown_is_one_shared_bucket(self):
        for number in range(2,6):create_order_intent(self.db,signal_id=self.add_signal(number),notional_usd=15)
        self.assertEqual(create_order_intent(self.db,signal_id=self.add_signal(6),notional_usd=5).reason,'unclassified_sector_limit')
    def test_total_cap_includes_all_sectors(self):
        for number in range(2,22):
            self.assertEqual(create_order_intent(self.db,signal_id=self.add_signal(number,f'Sector {number//4}'),notional_usd=15).action,'created')
        self.assertEqual(create_order_intent(self.db,signal_id=self.add_signal(22,'Other'),notional_usd=5).reason,'portfolio_notional_limit')
    def test_old_strategy_lots_count_against_new_version(self):
        create_order_intent(self.db,signal_id='signal-5',notional_usd=15)
        self.db.execute("INSERT INTO strategy_versions SELECT 'strategy-v2',name,status,config_json,'hash2',created_at,promoted_at FROM strategy_versions")
        self.db.execute("UPDATE signals SET strategy_version_id='strategy-v2' WHERE id IN ('signal-21','signal-63')")
        create_order_intent(self.db,signal_id='signal-21',notional_usd=15)
        self.assertEqual(create_order_intent(self.db,signal_id='signal-63',notional_usd=5).reason,'ticker_notional_limit')
    def test_two_workers_cannot_overreserve(self):
        import tempfile, sqlite3, threading
        from pathlib import Path
        from concurrent.futures import ThreadPoolExecutor
        self.db.execute("UPDATE strategy_versions SET config_json=?",(json.dumps({'entry_policy':{'enabled':True},'portfolio':{'maximum_notional_usd':15,'maximum_sector_notional_usd':60}}),))
        self.db.commit()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'concurrent.db'
            saved=sqlite3.connect(path);self.db.backup(saved);saved.close()
            barrier=threading.Barrier(2)
            def attempt(signal):
                db=sqlite3.connect(path,timeout=5);db.row_factory=sqlite3.Row
                barrier.wait()
                try:return create_order_intent(db,signal_id=signal,notional_usd=15).action
                finally:db.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(attempt,['signal-5','signal-21']))
            self.assertEqual(sorted(results),['created','rejected'])

class PolicyReleaseTests(unittest.TestCase):
    def test_new_policy_is_immutable_and_preserves_baseline(self):
        from stock_watch_worker.database import register_strategy
        from stock_watch_worker.config import load_strategy_document
        from stock_watch_worker.assessment_release import install_policy
        case=scan_tests.ScanExecutorTests();case.setUp()
        try:
            doc=json.loads(scan_tests.STRATEGY_PATH.read_text());doc.update(id='sp500-long-paper-v1',status='paper')
            register_strategy(case.connection,load_strategy_document(doc))
            install_policy(case.connection);install_policy(case.connection)
            new=json.loads(case.connection.execute("SELECT config_json FROM strategy_versions WHERE id='sp500-long-paper-v2'").fetchone()[0])
            self.assertEqual(new['portfolio'],{'maximum_notional_usd':300,'maximum_sector_notional_usd':60})
            self.assertEqual(new['weights'],doc['weights']);self.assertEqual(new['qualification'],doc['qualification'])
            for field,value in [('maximum_notional_usd',float('nan')),('maximum_sector_notional_usd',61)]:
                bad=json.loads(json.dumps(new));bad['portfolio'][field]=value
                with self.assertRaises(ValueError):load_strategy_document(bad)
            self.assertEqual(case.connection.execute('SELECT COUNT(*) FROM strategy_versions').fetchone()[0],2)
        finally:case.tearDown()
    def test_sector_import_uses_validated_labels(self):
        from stock_watch_worker.instrument_context import update_sectors
        case=order_tests.PaperOrderTests();case.setUp()
        try:
            self.assertEqual(update_sectors(case.connection,'Symbol,GICS Sector\nAAPL,Information Technology\nBOGUS,Technology\n',captured_at='2026-08-20',source='approved'),1)
            self.assertEqual(case.connection.execute('SELECT sector FROM instrument_context').fetchone()[0],'Information Technology')
        finally:case.tearDown()
