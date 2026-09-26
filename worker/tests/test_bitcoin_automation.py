import json
import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from stock_watch_worker.database import connect, apply_migrations
from stock_watch_worker.systems.automation_config import BitcoinConfig
from stock_watch_worker.systems.engine import SystemConfig, canonical
from stock_watch_worker.systems.timeframes import advance, boundary, deadline, evidence_expiry, next_review
from stock_watch_worker.systems.history import connect_history, import_rows, replay_bars
from stock_watch_worker.systems.research import register_version
from stock_watch_worker.systems.evaluation import queue, run_one, windows, summarize, finish, schedule
from stock_watch_worker.systems.coordinator import fund, reserve, apply_fill, tick, sync_orders
from stock_watch_worker.systems.automation_replay import replay, source_key, PROFILES

UTC=timezone.utc
NOW=datetime(2026,9,26,12,tzinfo=UTC)


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.temp.name)/'app.db'); apply_migrations(self.db)
        self.history=connect_history(Path(self.temp.name)/'history.db')
        self.config=BitcoinConfig('bitcoin',fast=5,slow=6,entry=6,exit=5,timeframe='1Min',holding_count=1,holding_unit='minutes')
        self.version=register_version(self.db,self.config)
        self.db.execute('INSERT INTO btc_enrollments(version_id,enrolled_at,approved_at) VALUES (?,?,?)',(self.version,NOW.isoformat(),NOW.isoformat())); self.db.commit()

    def tearDown(self):
        self.history.close(); self.db.close(); self.temp.cleanup()

    def broker(self):
        from unittest.mock import Mock
        broker=Mock(); broker.account.return_value={'id':'paper','cash':'300'}
        broker.positions.return_value=[]; broker.open_orders.return_value=[]; broker.fees.return_value=[]; broker.fills.return_value=[]
        broker.quote.return_value={'t':NOW.isoformat(),'bp':100,'ap':100,'bs':10,'as':10}
        broker.metadata.return_value={'min_trade_increment':'.00000001','min_order_size':'.00001'}
        return broker

    def qualify(self):
        eid=queue(self.db,self.version,NOW)
        with self.db:
            self.db.execute("UPDATE btc_qualifications SET status='qualified',evaluation_id=? WHERE version_id=?",(eid,self.version))
            for i in range(721):
                at=(NOW-timedelta(hours=i)).isoformat()
                self.db.execute('INSERT INTO btc_forward VALUES (?,?,?,?)',(self.version,at,300,'{}'))
            self.db.execute('INSERT INTO btc_health VALUES (?,?,NULL)',('data',NOW.isoformat()))
            self.db.execute('INSERT INTO btc_health VALUES (?,?,NULL)',('forward:'+self.version,NOW.isoformat()))
        with self.db:self.db.execute('UPDATE btc_allocations SET started_at=? WHERE version_id=?',(NOW.isoformat(),self.version))
        return eid

    def test_funding_and_qualification_are_not_initial_start_authority(self):
        from stock_watch_worker.systems.coordinator import eligible
        fund(self.db,self.broker(),[self.version],NOW)
        self.assertIsNone(self.db.execute('SELECT started_at FROM btc_allocations').fetchone()[0])
        eid=self.qualify()
        with self.db:self.db.execute('UPDATE btc_allocations SET started_at=NULL')
        self.assertIsNone(eligible(self.db,self.version,NOW))
        with self.assertRaisesRegex(ValueError,'qualified and approved'):
            reserve(self.db,self.version,'buy','.1',100,NOW,eid,'not explicitly started')
        with self.db:self.db.execute('UPDATE btc_allocations SET started_at=?',(NOW.isoformat(),))
        self.assertEqual(eligible(self.db,self.version,NOW),eid)

    def test_calendar_month_clamp_week_boundary_and_independent_hold(self):
        self.assertEqual(deadline(datetime(2024,1,31,tzinfo=UTC),1,'months'),datetime(2024,2,29,tzinfo=UTC))
        self.assertEqual(boundary(NOW,'1Week'),datetime(2026,9,21,tzinfo=UTC))
        self.assertEqual(advance(datetime(2026,12,1,tzinfo=UTC),'1Month'),datetime(2027,1,1,tzinfo=UTC))
        for frame in ('1Min','5Min','15Min','1Hour','4Hour','1Day','1Week','1Month'):
            c=BitcoinConfig('bitcoin',timeframe=frame,holding_count=12,holding_unit='months')
            self.assertEqual(c.holding_count,12)
        with self.assertRaises(ValueError): BitcoinConfig('bitcoin',holding_count=13,holding_unit='months')
        with self.assertRaises(ValueError): BitcoinConfig('bitcoin',allocation=.6)
        with self.assertRaises(ValueError): BitcoinConfig('bitcoin',holding_count=366,holding_unit='days')

    def test_v1_hash_and_v2_contract_are_distinct(self):
        self.assertEqual(SystemConfig('bitcoin').sha256,'e664521e08effecaea9a67e44b54ccf858675184860ad186493eb0e8f4a5856d')
        self.assertNotEqual(BitcoinConfig('bitcoin').sha256,SystemConfig('bitcoin').sha256)

    def test_exactly_100_distinct_scenarios_and_at_least_five_independent_windows(self):
        eid=queue(self.db,self.version,NOW)
        self.assertIsNone(queue(self.db,self.version,NOW))
        rows=self.db.execute('SELECT * FROM btc_scenarios WHERE evaluation_id=?',(eid,)).fetchall()
        self.assertEqual(len(rows),100)
        self.assertEqual(len({(r['starts_at'],r['ends_at'],r['profile']) for r in rows}),100)
        independent=0; end=None
        for start,finish_at in windows(self.config,NOW):
            if end is None or start>=end: independent+=1; end=finish_at
        self.assertGreaterEqual(independent,5)

    def test_missing_data_finishes_suite_but_never_qualifies_and_reuses_cache(self):
        eid=queue(self.db,self.version,NOW)
        for _ in range(100): run_one(self.db,self.history,NOW)
        result=self.db.execute('SELECT * FROM btc_evaluations WHERE id=?',(eid,)).fetchone()
        self.assertEqual(result['progress'],100)
        self.assertFalse(json.loads(result['result_json'])['passed'])
        self.assertEqual(self.db.execute('SELECT status FROM btc_qualifications').fetchone()[0],'collecting')
        # Crash/retry of the same frozen scenario verifies and reuses content.
        with self.db:
            self.db.execute("UPDATE btc_evaluations SET status='running' WHERE id=?",(eid,))
            self.db.execute("UPDATE btc_scenarios SET status='queued' WHERE id=(SELECT id FROM btc_scenarios LIMIT 1)")
        run_one(self.db,self.history,NOW)
        self.assertEqual(self.db.execute('SELECT SUM(reused) FROM btc_scenarios').fetchone()[0],1)

    def test_unique_trades_are_not_multiplied_by_windows_or_profiles(self):
        results=[]
        for i,(start,end) in enumerate(windows(self.config,NOW)):
            for profile in PROFILES:
                results.append({'profile':profile,'starts_at':start.isoformat(),'ends_at':end.isoformat(),'trades':[{'id':'same','pnl':1}],
                                'valid':True,'net_return':.1,'drawdown':.01,'exposure':.5,'turnover':1,'costs':1})
        summary=summarize(results)
        self.assertEqual(summary['unique_trades'],1)
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['profitable_windows'],1)

    def test_later_revisions_do_not_rewrite_replay_inputs(self):
        at=NOW-timedelta(minutes=2)
        row={'at':at.isoformat(),'open':100,'high':101,'low':99,'close':100,'volume':1}
        import_rows(self.history,'1Min',[row],(at+timedelta(seconds=5)).isoformat())
        row['close']=101
        import_rows(self.history,'1Min',[row],NOW.isoformat())
        rows=list(replay_bars(self.history,'1Min',at.isoformat(),NOW.isoformat(),NOW.isoformat()))
        self.assertEqual(rows[0]['close'],100)
        key=source_key(self.history,self.config,at.isoformat(),NOW.isoformat(),NOW.isoformat(),'base')
        with self.history: self.history.execute('INSERT INTO quotes VALUES (?,?,?,?,?,?)',(at.isoformat(),at.isoformat(),99,101,1,1))
        self.assertNotEqual(key,source_key(self.history,self.config,at.isoformat(),NOW.isoformat(),NOW.isoformat(),'base'))

    def test_shared_funding_reservations_and_ownership(self):
        versions=[self.version]
        for n in range(4):
            config=BitcoinConfig('bitcoin',fast=5,slow=7+n,entry=6,exit=5)
            version=register_version(self.db,config); versions.append(version)
            with self.db: self.db.execute('INSERT INTO btc_enrollments(version_id,enrolled_at,approved_at) VALUES (?,?,?)',(version,NOW.isoformat(),NOW.isoformat()))
        fund(self.db,self.broker(),versions,NOW)
        self.assertEqual([float(r[0]) for r in self.db.execute('SELECT budget FROM btc_allocations')],[60]*5)
        eid=self.qualify()
        oid=reserve(self.db,self.version,'buy','.25',100,NOW,eid,'test')
        with self.assertRaises(ValueError): reserve(self.db,self.version,'buy','.25',100,NOW,eid,'duplicate')
        with self.assertRaises(ValueError): reserve(self.db,versions[1],'sell','.25',100,NOW,None,'not owned')
        order=self.db.execute('SELECT * FROM btc_orders WHERE id=?',(oid,)).fetchone()
        apply_fill(self.db,order,{'id':'broker-1','status':'partially_filled','filled_qty':'.1','filled_avg_price':'100'},NOW)
        allocation=self.db.execute('SELECT * FROM btc_allocations WHERE version_id=?',(self.version,)).fetchone()
        self.assertAlmostEqual(float(allocation['cash']),50)
        self.assertAlmostEqual(float(allocation['quantity']),.09975)
        self.assertEqual(instant_for_test(allocation['exit_due_at']),NOW+timedelta(minutes=1))
        order=self.db.execute('SELECT * FROM btc_orders WHERE id=?',(oid,)).fetchone()
        apply_fill(self.db,order,{'id':'broker-1','status':'filled','filled_qty':'.25','filled_avg_price':'100'},NOW+timedelta(seconds=10))
        allocation=self.db.execute('SELECT * FROM btc_allocations WHERE version_id=?',(self.version,)).fetchone()
        self.assertAlmostEqual(float(allocation['cash']),35)
        self.assertEqual(instant_for_test(allocation['exit_due_at']),NOW+timedelta(minutes=1))

    def test_expiry_cancels_entries_but_deadline_exits_survive_quote_outage(self):
        broker=self.broker(); fund(self.db,broker,[self.version],NOW)
        with self.db:
            self.db.execute("UPDATE btc_allocations SET quantity='1',cash='200',exit_due_at=?",((NOW-timedelta(minutes=1)).isoformat(),))
        broker.quote.side_effect=ValueError('quote outage'); broker.lookup.return_value=None
        broker.submit.return_value={'id':'sell-1','status':'filled','filled_qty':'1','filled_avg_price':'100'}
        tick(self.db,self.history,broker,NOW)
        broker.submit.assert_called_once()
        self.assertEqual(broker.submit.call_args.args[1],'sell')
        self.assertEqual(self.db.execute('SELECT quantity FROM btc_allocations').fetchone()[0],'0')

    def test_expiration_blocks_entries(self):
        eid=self.qualify(); schedule(self.db,NOW+timedelta(hours=37))
        self.assertEqual(self.db.execute('SELECT status FROM btc_qualifications').fetchone()[0],'suspended')
        self.assertEqual(evidence_expiry(NOW,'1Hour'),NOW+timedelta(hours=36))
        self.assertEqual(evidence_expiry(NOW,'1Day'),NOW+timedelta(days=8))
        self.assertEqual(next_review(NOW,'1Month'),datetime(2026,10,1,0,15,tzinfo=UTC))

    def test_uncertain_submit_retry_uses_durable_identifier(self):
        broker=self.broker(); fund(self.db,broker,[self.version],NOW); eid=self.qualify()
        oid=reserve(self.db,self.version,'buy','.1',100,NOW,eid,'test')
        broker.lookup.return_value=None; broker.submit.side_effect=TimeoutError('lost response')
        with self.assertRaises(TimeoutError): sync_orders(self.db,broker,NOW,True)
        broker.lookup.return_value={'id':'existing','status':'filled','filled_qty':'.1','filled_avg_price':'100'}
        sync_orders(self.db,broker,NOW,True)
        broker.submit.assert_called_once()
        self.assertEqual(broker.lookup.call_args.args[0],oid)


    def observed_data(self):
        import math
        start=NOW-timedelta(minutes=180)
        for i in range(180):
            at=start+timedelta(minutes=i); price=100+5*math.sin(i/3)
            import_rows(self.history,'1Min',[{'at':at.isoformat(),'open':price,'high':price+1,'low':price-1,'close':price,'volume':10}],(at+timedelta(seconds=5)).isoformat())
            with self.history:
                for second in range(0,60,10):
                    stamp=(at+timedelta(seconds=second)).isoformat()
                    self.history.execute('INSERT INTO quotes VALUES (?,?,?,?,?,?)',(stamp,stamp,price-.01,price+.01,.1,.1))
        metadata={'min_order_size':'.00001','min_trade_increment':'.00000001'}
        with self.history: self.history.execute('INSERT INTO metadata VALUES (?,?)',(start.isoformat(),canonical(metadata)))
        return metadata

    def test_observed_replay_waits_for_subsequent_quote_and_missing_bar_invalidates(self):
        metadata=self.observed_data(); start=NOW-timedelta(minutes=60)
        result=replay(self.history,self.config,start.isoformat(),NOW.isoformat(),NOW.isoformat(),'base',metadata=metadata)
        self.assertTrue(result['valid'])
        self.assertGreater(len(result['trades']),0)
        for trade in result['trades']:
            self.assertGreater(instant_for_test(trade['entered_at']),instant_for_test(trade['id'])+timedelta(seconds=5))
        with self.history: self.history.execute('DELETE FROM bars WHERE at=?',((NOW-timedelta(minutes=30)).isoformat(),))
        self.assertFalse(replay(self.history,self.config,start.isoformat(),NOW.isoformat(),NOW.isoformat(),'base',metadata=metadata)['valid'])

    def test_uncertain_entry_is_not_forgotten_when_qualification_disappears(self):
        broker=self.broker(); fund(self.db,broker,[self.version],NOW); eid=self.qualify()
        oid=reserve(self.db,self.version,'buy','.1',100,NOW,eid,'test')
        broker.lookup.return_value=None; broker.submit.side_effect=TimeoutError('lost response')
        with self.assertRaises(TimeoutError): sync_orders(self.db,broker,NOW,True)
        with self.assertRaises(ValueError): sync_orders(self.db,broker,NOW+timedelta(minutes=2),False)
        self.assertEqual(self.db.execute('SELECT status FROM btc_orders WHERE id=?',(oid,)).fetchone()[0],'submitting')
        broker.submit.assert_called_once()

    def test_aggregate_day_fees_are_attributed_to_actual_fills(self):
        from stock_watch_worker.systems.automation_fees import capture
        broker=self.broker(); fund(self.db,broker,[self.version],NOW); eid=self.qualify()
        oid=reserve(self.db,self.version,'buy','.1',100,NOW,eid,'test')
        order=self.db.execute('SELECT * FROM btc_orders WHERE id=?',(oid,)).fetchone()
        apply_fill(self.db,order,{'id':'broker-1','status':'filled','filled_qty':'.1','filled_avg_price':'100'},NOW)
        broker.fills.return_value=[{'id':'fill-1','order_id':'broker-1','symbol':'BTC/USD','side':'buy','qty':'.1','price':'100','transaction_time':NOW.isoformat()}]
        broker.fees.return_value=[{'id':'fee-1','date':NOW.date().isoformat(),'symbol':'BTCUSD','qty':'-.00025','net_amount':'0','status':'executed'}]
        account=self.db.execute('SELECT * FROM btc_accounts').fetchone()
        capture(self.db,broker,account,NOW+timedelta(days=1))
        row=self.db.execute('SELECT * FROM btc_fee_allocations').fetchone()
        self.assertEqual(row['order_id'],oid)
        self.assertAlmostEqual(float(row['quantity_fee']),.00025)
        self.assertEqual(row['method'],'proportional_utc_day_quantity')
        capture(self.db,broker,account,NOW+timedelta(days=1))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM btc_fee_allocations').fetchone()[0],1)

    def test_five_system_complete_suites_keep_main_database_writable(self):
        import time
        metadata=self.observed_data()
        versions=[self.version]
        for i in range(4):
            version=register_version(self.db,BitcoinConfig('bitcoin',fast=5,slow=7+i,entry=6,exit=5,timeframe='1Min',holding_count=1,holding_unit='minutes'))
            with self.db: self.db.execute('INSERT INTO btc_enrollments(version_id,enrolled_at,approved_at) VALUES (?,?,?)',(version,NOW.isoformat(),NOW.isoformat()))
            versions.append(version)
        broker=self.broker(); fund(self.db,broker,versions,NOW)
        started=time.monotonic(); longest=0
        for _ in range(500):
            self.assertTrue(run_one(self.db,self.history,NOW))
            before=time.monotonic()
            with self.db: self.db.execute("INSERT INTO system_audit(at,action,entity_id,payload_json) VALUES (?,'stock_load_probe','test','{}')",(NOW.isoformat(),))
            longest=max(longest,time.monotonic()-before)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM btc_evaluations WHERE status='succeeded' AND progress=100").fetchone()[0],5)
        self.assertLess(longest,2)
        self.assertEqual(len(broker.submit.call_args_list),0)
        print(canonical({'five_system_scenarios':500,'seconds':round(time.monotonic()-started,3),'max_stock_write_seconds':round(longest,6)}))

    def test_concurrent_reservations_cannot_spend_the_same_allocation(self):
        from concurrent.futures import ThreadPoolExecutor
        broker=self.broker(); fund(self.db,broker,[self.version],NOW); eid=self.qualify()
        path=Path(self.temp.name)/'app.db'
        def attempt():
            db=connect(path)
            try:
                reserve(db,self.version,'buy','.1',100,NOW,eid,'race')
                return True
            except ValueError: return False
            finally: db.close()
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sorted(results),[False,True])

    def test_recovery_needs_two_passing_scheduled_evaluations(self):
        eid=self.qualify()
        with self.db: self.db.execute("UPDATE btc_qualifications SET failed_once=1,status='suspended',pass_streak=0")
        passing={'passed':True,'reasons':[]}
        # Two distinct scheduled suites; a repeated finish cannot increment twice.
        for i in range(2):
            if i:
                eid=queue(self.db,self.version,NOW+timedelta(days=i))
            evaluation=self.db.execute('SELECT * FROM btc_evaluations WHERE id=?',(eid,)).fetchone()
            with self.db: self.db.execute("UPDATE btc_scenarios SET result_json=?,status='succeeded' WHERE evaluation_id=?",(canonical({'valid':True}),eid))
            with patch('stock_watch_worker.systems.evaluation.summarize',return_value={**passing,'reasons':[]}), patch('stock_watch_worker.systems.evaluation.forward_ready',return_value=(True,'')):
                finish(self.db,evaluation,NOW+timedelta(days=i))
                finish(self.db,evaluation,NOW+timedelta(days=i))
            row=self.db.execute('SELECT * FROM btc_qualifications').fetchone()
            self.assertEqual(row['pass_streak'],i+1)
            self.assertEqual(row['status'],'qualified' if i else 'suspended')


    def test_fee_endpoint_failure_does_not_disable_price_risk_exits(self):
        broker=self.broker(); fund(self.db,broker,[self.version],NOW)
        with self.db:
            self.db.execute("UPDATE btc_allocations SET quantity='1',cash='200',entry_at=?,exit_due_at=?",(NOW.isoformat(),(NOW+timedelta(days=1)).isoformat()))
        broker.fills.side_effect=ValueError('activities unavailable')
        broker.quote.return_value={'t':NOW.isoformat(),'bp':50,'ap':50,'bs':10,'as':10}
        broker.lookup.return_value=None
        broker.submit.return_value={'id':'risk-sell','status':'filled','filled_qty':'1','filled_avg_price':'50'}
        tick(self.db,self.history,broker,NOW)
        self.assertEqual(broker.submit.call_args.args[1],'sell')
        self.assertEqual(self.db.execute('SELECT risk_paused FROM btc_accounts').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT risk_paused FROM btc_allocations').fetchone()[0],1)

    def test_windows_expand_with_observed_history_without_using_profit(self):
        short=windows(self.config,NOW)
        long=windows(self.config,NOW,NOW-timedelta(days=90))
        self.assertGreater(long[0][1]-long[0][0],short[0][1]-short[0][0])
        self.assertGreaterEqual(long[0][0],NOW-timedelta(days=90))


    def test_revisions_affect_only_decisions_after_their_publication(self):
        metadata=self.observed_data(); bar_at=(NOW-timedelta(minutes=50)).isoformat()
        revised=json.loads(self.history.execute('SELECT payload_json FROM bars WHERE at=?',(bar_at,)).fetchone()[0])
        revised.update(close=200,high=201,available_at=(NOW-timedelta(minutes=30)).isoformat())
        import_rows(self.history,'1Min',[revised],revised['available_at'])
        seen=[]
        def inspect(config,history,held):
            value=next((r['close'] for r in history if r['at']==bar_at),None)
            seen.append((instant_for_test(history[-1]['at']),value))
            return 'hold','test'
        with patch('stock_watch_worker.systems.automation_replay.decision',side_effect=inspect):
            replay(self.history,self.config,(NOW-timedelta(minutes=60)).isoformat(),NOW.isoformat(),NOW.isoformat(),'base',metadata=metadata)
        self.assertTrue(any(v==200 for at,v in seen if at>=NOW-timedelta(minutes=30)))
        self.assertFalse(any(v==200 for at,v in seen if at<NOW-timedelta(minutes=30)))


def instant_for_test(value): return datetime.fromisoformat(value)
