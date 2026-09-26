import json
import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from stock_watch_worker.database import apply_migrations, connect
from stock_watch_worker.http import HttpResponse
from stock_watch_worker.systems.engine import SystemConfig, canonical, decision, replay, validate_dataset
from stock_watch_worker.systems.research import register_version, register_dataset, run_next, evaluate
from stock_watch_worker.systems.bitcoin import BitcoinMonitor, validate_address
from stock_watch_worker.systems.broker import CryptoBroker, rounded_quantity
from stock_watch_worker.systems.runtime import start_shadow, activate, order_intent, tick
from stock_watch_worker.systems.stocks import legacy_entries_disabled, system_positions


def dataset(prices, asset='bitcoin', symbols=None):
    rows=[]
    start=datetime(2024,1,1,tzinfo=timezone.utc)
    for i,price in enumerate(prices):
        at=start+timedelta(hours=i)
        for symbol in (symbols or ['BTC/USD']):
            rows.append({'symbol':symbol,'at':at.isoformat(),'available_at':at.isoformat(),
                         'open':price,'high':price,'low':price,'close':price,'sector':'Technology',
                         'quote':{'at':(at+timedelta(seconds=1)).isoformat(),'bid':price,'ask':price}})
    return {'schema_version':1,'asset':asset,'manifest':{'provider':'fixture','venue':'fixture','fidelity':'intraday','point_in_time_membership':True},'bars':rows}


class RulesTests(unittest.TestCase):
    def test_breakout_excludes_current_bar(self):
        cfg=SystemConfig('bitcoin','breakout',entry=6,exit=5)
        rows=dataset([100]*6+[110])['bars']
        self.assertEqual(decision(cfg,rows,False)[0],'buy')
        self.assertEqual(decision(cfg,rows,True)[0],'hold')
        self.assertEqual(decision(cfg,rows+dataset([90])['bars'],True)[0],'sell')

    def test_crossover_is_an_event_not_persistent_buy(self):
        cfg=SystemConfig('bitcoin','trend',fast=5,slow=6)
        rows=dataset([100]*6+[110,111])['bars']
        self.assertEqual(decision(cfg,rows[:-1],False)[0],'buy')
        self.assertEqual(decision(cfg,rows,False)[0],'hold')

    def test_cash_constrained_shared_stock_budget_and_sector(self):
        data=dataset([100]*6+[110,111,112], 'stocks',[f'S{i}' for i in range(25)])
        result=replay(SystemConfig('stocks','breakout',entry=6,exit=5,allocation=1),data)
        self.assertLessEqual(sum(p['cost'] for p in result['open_positions'].values()),60.000001)
        self.assertGreaterEqual(min(p['cash'] for p in result['equity_curve']),0)
        self.assertEqual(len(result['fills']),4)

    def test_fees_stress_and_future_execution(self):
        data=dataset([100]*6+[110]*6+[90]*6)
        cfg=SystemConfig('bitcoin','breakout',entry=6,exit=5)
        base=replay(cfg,data)
        stress=replay(cfg,data,cost_multiplier=2)
        self.assertGreater(base['fees'],0)
        self.assertLess(stress['ending_equity'],base['ending_equity'])
        self.assertEqual(base['closed_trades'],1)
        self.assertGreater(base['fills'][0]['at'],data['bars'][6]['at'])

    def test_rejects_lookahead_duplicate_and_nan(self):
        for change in ('future','duplicate','nan','samequote'):
            data=dataset([100]*7)
            if change=='future': data['bars'][0]['available_at']=data['bars'][1]['at']
            if change=='duplicate': data['bars'][1]=data['bars'][0]
            if change=='nan': data['bars'][0]['close']=float('nan')
            if change=='samequote': data['bars'][0]['quote']['at']=data['bars'][0]['at']
            with self.assertRaises(ValueError): validate_dataset(data,'bitcoin')

    def test_hourly_gap_restarts_indicators(self):
        data=dataset([100]*6+[110]*3)
        del data['bars'][5]
        result=replay(SystemConfig('bitcoin','breakout',entry=6,exit=5),data)
        self.assertFalse(result['fills'])
        self.assertTrue(any('gap' in s for s in result['warnings']))

    def test_risk_breach_exits_and_stays_paused(self):
        data=dataset([100]*6+[110,111,60,120,130,140,150,160,170])
        result=replay(SystemConfig('bitcoin','breakout',entry=6,exit=5),data)
        self.assertTrue(result['risk_paused'])
        self.assertEqual([f['side'] for f in result['fills']],['buy','sell'])
        self.assertFalse(result['open_positions'])

    def test_cancel(self):
        with self.assertRaises(InterruptedError): replay(SystemConfig('bitcoin'),dataset([100]),canceled=lambda:True)

    def test_insufficient_coverage_has_no_fake_folds(self):
        result=evaluate(SystemConfig('bitcoin'),dataset([100]*110))
        self.assertEqual(result['folds'],[])
        self.assertEqual(result['holdout_status'],'insufficient_history')
        self.assertFalse(result['promotion_ready'])

    def test_config_bounds(self):
        for kwargs in ({'fast':True},{'fast':100},{'allocation':float('nan')},{'asset':'crypto'}):
            with self.assertRaises(ValueError): SystemConfig(**{'asset':'bitcoin',**kwargs})


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.temp.name)/'test.db')
        apply_migrations(self.db)
    def tearDown(self):
        self.db.close();self.temp.cleanup()
    def test_immutable_version_and_legacy_default(self):
        v=register_version(self.db,SystemConfig('stocks'))
        self.assertFalse(legacy_entries_disabled(self.db))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('UPDATE system_versions SET template=? WHERE id=?',('breakout',v))
        self.db.rollback()
        self.assertEqual(system_positions(self.db),{})
    def test_job_hash_verification(self):
        v=register_version(self.db,SystemConfig('bitcoin'))
        path=Path(self.temp.name)/'source.json';path.write_text(canonical(dataset([100]*110)))
        d=register_dataset(self.db,path,Path(self.temp.name)/'datasets')
        with self.db:
            self.db.execute("INSERT INTO system_runs(id,version_id,dataset_id,status,created_at) VALUES ('r',?,?,'queued','now')",(v,d))
        stored=Path(self.db.execute('SELECT path FROM system_datasets').fetchone()[0]);stored.write_text('{}')
        run_next(self.db)
        row=self.db.execute('SELECT * FROM system_runs').fetchone()
        self.assertEqual(row['status'],'failed');self.assertIn('hash',row['error'])
    def test_successful_job(self):
        v=register_version(self.db,SystemConfig('bitcoin'))
        path=Path(self.temp.name)/'source.json';path.write_text(canonical(dataset([100]*110)))
        d=register_dataset(self.db,path,Path(self.temp.name)/'datasets')
        with self.db: self.db.execute("INSERT INTO system_runs(id,version_id,dataset_id,status,created_at) VALUES ('r',?,?,'queued','now')",(v,d))
        self.assertEqual(run_next(self.db),'r')
        self.assertEqual(self.db.execute('SELECT status FROM system_runs').fetchone()[0],'succeeded')
    def test_activation_requires_actual_forward_observations(self):
        v=register_version(self.db,SystemConfig('bitcoin'));d=start_shadow(self.db,v)
        with self.assertRaisesRegex(ValueError,'30 distinct'): activate(self.db,d,object(),d)
    def test_stock_cutover_persists_through_pause(self):
        v=register_version(self.db,SystemConfig('stocks'));d=start_shadow(self.db,v)
        with self.db: self.db.execute("INSERT INTO system_stock_control VALUES (1,?,'now')",(d,))
        self.assertTrue(legacy_entries_disabled(self.db))
    def test_unknown_submission_reuses_durable_identity(self):
        v=register_version(self.db,SystemConfig('bitcoin'));d=start_shadow(self.db,v)
        class Broker:
            found=None
            calls=0
            def quote(self,now):return {'ap':100,'bp':100,'t':now.isoformat()}
            def lookup(self,identifier): return self.found
            def submit(self,identifier,side,qty):
                self.calls+=1
                self.found={'id':'broker','status':'filled','filled_qty':qty,'filled_avg_price':'100'}
                raise TimeoutError('response lost')
        broker=Broker()
        with self.assertRaises(TimeoutError): order_intent(self.db,d,'buy','1','2024-01-01T00:00:00+00:00',broker)
        order_intent(self.db,d,'buy','1','2024-01-01T00:00:00+00:00',broker)
        self.assertEqual(broker.calls,1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM system_orders').fetchone()[0],1)


class AddressTests(unittest.TestCase):
    def test_valid_mainnet_base58(self):
        self.assertEqual(validate_address('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'),'1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa')
    def test_rejects_invalid_checksum_testnet_and_secret(self):
        for address in ['1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb','tb1qanything','xpub123','seed words','bc1qinvalid']:
            with self.assertRaises(ValueError): validate_address(address)
    def test_plain_text_tip_response(self):
        class Transport:
            def request(self,*a,**k):return HttpResponse(200,{},b'abc123')
        self.assertEqual(BitcoinMonitor(Transport()).get('blocks/tip/hash',text=True),'abc123')
    def test_crypto_precision(self):
        self.assertEqual(rounded_quantity('0.123456','0.0001'),'0.1234')
    def test_crypto_adapter_never_uses_stock_clock_or_live_host(self):
        class Transport:
            urls=[]
            def request(self,method,url,**kwargs):
                self.urls.append(url)
                return HttpResponse(200,{},b'{"id":"test"}')
        t=Transport();broker=CryptoBroker(t,key='bitcoin-key',secret='secret')
        broker.submit('id','buy','0.001')
        self.assertEqual(t.urls,['https://paper-api.alpaca.markets/v2/orders'])


if __name__=='__main__': unittest.main()

class RiskAndMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.temp.name)/'test.db');apply_migrations(self.db)
    def tearDown(self):
        self.db.close();self.temp.cleanup()
    def test_paused_account_can_exit_when_quote_feed_is_down(self):
        from stock_watch_worker.systems.runtime import _tick_one
        version=register_version(self.db,SystemConfig('bitcoin'))
        deployment=start_shadow(self.db,version)
        at='2024-01-01T00:00:00+00:00'
        with self.db:
            self.db.execute("UPDATE system_deployments SET mode='paused',account_id='paper',state_json=? WHERE id=?",(canonical({'paper_started_at':at}),deployment))
            self.db.execute("INSERT INTO system_orders(id,deployment_id,symbol,side,request_json,status,filled_qty,filled_price,created_at,updated_at) VALUES ('old',?,'BTC/USD','buy','{}','filled','1','100',?,?)",(deployment,at,at))
        class Broker:
            submitted=[]
            def account(self):return {'id':'paper','cash':'200'}
            def positions(self):return [{'symbol':'BTCUSD','qty':'1'}]
            def open_orders(self):return []
            def fees(self,at):return []
            def quote(self,now):raise ValueError('Feed down')
            def metadata(self):return {'min_order_size':'0.0001','min_trade_increment':'0.0001'}
            def lookup(self,id):return None
            def submit(self,id,side,qty):
                self.submitted.append((side,qty))
                return {'id':'exit','status':'filled','filled_qty':qty,'filled_avg_price':'90'}
        broker=Broker()
        row=self.db.execute('SELECT d.*,v.config_json FROM system_deployments d JOIN system_versions v ON v.id=d.version_id').fetchone()
        _tick_one(self.db,broker,row,datetime(2024,1,2,tzinfo=timezone.utc))
        self.assertEqual(broker.submitted,[('sell','1')])
    def test_pause_cancels_unsent_buy_instead_of_resubmitting(self):
        from stock_watch_worker.systems.runtime import reconcile_orders
        version=register_version(self.db,SystemConfig('bitcoin'));deployment=start_shadow(self.db,version)
        with self.db:self.db.execute("INSERT INTO system_orders(id,deployment_id,symbol,side,request_json,created_at,updated_at) VALUES ('pending',?,'BTC/USD','buy','{\"qty\":\"1\"}','2024-01-01T00:00:00+00:00','now')",(deployment,))
        class Broker:
            def lookup(self,id):return None
            def submit(self,*args):raise AssertionError('Must not submit a paused buy')
        reconcile_orders(self.db,deployment,Broker(),allow_entries=False)
        self.assertEqual(self.db.execute('SELECT status FROM system_orders').fetchone()[0],'canceled')
    def test_minute_risk_quotes_can_exit_before_next_hour(self):
        data=dataset([100]*6+[110,110,110])
        start=datetime.fromisoformat(data['bars'][6]['at'])
        data['risk_quotes']=[{'at':(start+timedelta(minutes=i)).isoformat(),'bid':110 if i<5 else 60,'ask':110 if i<5 else 60} for i in range(1,60)]
        result=replay(SystemConfig('bitcoin','breakout',entry=6,exit=5),data)
        self.assertTrue(result['risk_paused'])
        self.assertEqual(result['fills'][-1]['reason'],'Minute portfolio drawdown exit')
        self.assertLess(result['fills'][-1]['at'],data['bars'][7]['at'])
    def test_reorg_is_recorded_and_network_backoff_prevents_repeated_requests(self):
        at=datetime(2024,1,1,tzinfo=timezone.utc)
        with self.db:self.db.execute("INSERT INTO bitcoin_observations(observed_at,kind,payload_json) VALUES (?,'network',?)",(at.isoformat(),canonical({'block':{'id':'old','height':10}})))
        class Monitor(BitcoinMonitor):
            def get(self,path,text=False):
                return {'blocks/tip/hash':'new','block/new':{'id':'new','height':11},'block-height/10':'replacement','mempool':{'count':1},'v1/fees/recommended':{'fastestFee':2}}[path]
        Monitor().collect(self.db,at+timedelta(minutes=1))
        latest=self.db.execute("SELECT payload_json FROM bitcoin_observations WHERE kind='network' ORDER BY observed_at DESC LIMIT 1").fetchone()[0]
        self.assertTrue(json.loads(latest)['reorg_detected'])
        class Failed(BitcoinMonitor):
            calls=0
            def get(self,*args,**kwargs):self.calls+=1;raise ValueError('429')
        failed=Failed();failed.collect(self.db,at+timedelta(minutes=2));failed.collect(self.db,at+timedelta(minutes=3))
        self.assertEqual(failed.calls,1)

class ReplayAccountingTests(unittest.TestCase):
    def test_partial_fills_do_not_spend_the_cash_twice(self):
        data=dataset([100]*6+[110]*8)
        for bar in data['bars']:bar['quote']['ask_size']=.2
        result=replay(SystemConfig('bitcoin','breakout',entry=6,exit=5),data)
        buys=[f for f in result['fills'] if f['side']=='buy']
        self.assertGreater(len(buys),1)
        self.assertTrue(all(f['qty']<=.2 for f in buys))
        self.assertGreaterEqual(min(p['cash'] for p in result['equity_curve']),0)
        self.assertLessEqual(sum(f['qty']*f['price'] for f in buys),150)
        gross=sum(f['qty'] for f in buys)
        self.assertAlmostEqual(result['open_positions']['BTC/USD']['qty'],gross*.9975)
    def test_split_preserves_value_and_adjusts_indicator_history(self):
        data=dataset([100]*6+[110,110,55,55],'stocks',['ABC'])
        at=data['bars'][8]['at']
        data['corporate_actions']=[{'type':'split','symbol':'ABC','at':at,'available_at':at,'ratio':2}]
        result=replay(SystemConfig('stocks','breakout',entry=6,exit=5),data)
        self.assertEqual(len(result['fills']),1)
        self.assertGreater(result['ending_equity'],299)
        self.assertAlmostEqual(result['open_positions']['ABC']['qty'],result['fills'][0]['qty']*2)
    def test_dividend_is_receivable_until_payment(self):
        data=dataset([100]*6+[110]*4,'stocks',['ABC'])
        at=data['bars'][8]['at']
        data['corporate_actions']=[{'type':'cash_dividend','symbol':'ABC','at':at,'available_at':at,'amount':1,'pay_at':data['bars'][9]['at']}]
        result=replay(SystemConfig('stocks','breakout',entry=6,exit=5),data)
        curve=result['equity_curve']
        before=[p for p in curve if p['at']==at][-1]
        after=curve[-1]
        self.assertGreater(after['cash'],before['cash'])

class StockCutoverTests(unittest.TestCase):
    def test_reviewed_cutover_keeps_legacy_strategy_rows_and_closes_entry_authority(self):
        from stock_watch_worker.systems.stocks import activate_stock
        with tempfile.TemporaryDirectory() as directory:
            db=connect(Path(directory)/'test.db');apply_migrations(db)
            v=register_version(db,SystemConfig('stocks'));deployment=start_shadow(db,v)
            with db:
                for day in range(1,21):
                    at=f'2024-01-{day:02d}T21:00:00+00:00'
                    db.execute('INSERT INTO system_observations(deployment_id,observed_at,kind,payload_json) VALUES (?,?,?,?)',(deployment,at,'shadow',canonical({'session':at[:10]})))
                db.execute("INSERT INTO system_datasets VALUES ('dataset','stocks','unused','sha','{}','now')")
                db.execute("INSERT INTO system_runs(id,version_id,dataset_id,status,created_at,finished_at,result_json) VALUES ('run',?,'dataset','succeeded','now','now',?)",(v,canonical({'folds':[{'test':{}}]})))
            class Broker:
                def account(self):return {'id':'stock-paper','cash':'300','equity':'300'}
                def positions(self):return []
                def open_orders(self):return []
            before=db.execute('SELECT COUNT(*) FROM paper_trade_lots').fetchone()[0]
            activate_stock(db,deployment,Broker(),deployment,datetime(2024,1,21,tzinfo=timezone.utc))
            self.assertTrue(legacy_entries_disabled(db))
            self.assertEqual(db.execute('SELECT mode FROM system_deployments').fetchone()[0],'paper')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM paper_trade_lots').fetchone()[0],before)
            db.close()

class StockRetryTests(unittest.TestCase):
    def test_unsubmitted_stock_entry_expires_before_retry(self):
        from stock_watch_worker.systems.stocks import reconcile
        with tempfile.TemporaryDirectory() as directory:
            db=connect(Path(directory)/'test.db');apply_migrations(db)
            deployment=start_shadow(db,register_version(db,SystemConfig('stocks')))
            with db:db.execute("INSERT INTO system_orders(id,deployment_id,symbol,side,request_json,created_at,updated_at) VALUES ('pending',?,'ABC','buy','{\"notional\":10}','2024-01-01T14:45:00+00:00','2024-01-01T14:45:00+00:00')",(deployment,))
            class Broker:
                def lookup(self,identifier):return None
                def submit(self,*args):raise AssertionError('Expired entry must not submit')
            reconcile(db,deployment,Broker(),now=datetime(2024,1,2,14,45,tzinfo=timezone.utc))
            self.assertEqual(db.execute('SELECT status FROM system_orders').fetchone()[0],'canceled')
            db.close()
