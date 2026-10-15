from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest
from stock_watch_worker.database import connect, apply_migrations
from stock_watch_worker.experiments import evidence
from stock_watch_worker.experiments.model import config, stamp, money, canonical, signal
from stock_watch_worker.experiments.store import preview, approve, controls
from stock_watch_worker.experiments.execution import reserve, sync, apply_response, active, available, release_settlement, position
from stock_watch_worker.experiments.engine import tick, valuation

NOW=datetime(2026,10,14,14,5,35,tzinfo=timezone.utc)

class Broker:
    def __init__(self,asset='stocks'):
        self.asset=asset; self.orders={}; self.posts=0; self.timeout=False; self.cancel_uncertain=False
    def account(self): return {'id':self.asset+'-paper','cash':'1000','status':'ACTIVE','currency':'USD'}
    def execution_check(self,request,account_id): return NOW,self.account()
    def preflight(self,symbols): return {'account_id':self.asset+'-paper','metadata':{s:{'quantity_increment':'0.000000001','minimum_quantity':'0.000000001','price_increment':'0.01'} for s in symbols}}
    def submit(self,request):
        self.posts+=1
        if self.timeout: raise TimeoutError('accepted POST response lost')
        row={**request,'id':'broker-'+request['client_order_id'],'status':'accepted','filled_qty':'0','filled_avg_price':None}
        self.orders[request['client_order_id']]=row; return row
    def lookup(self,key): return self.orders.get(key)
    def cancel(self,key):
        if self.cancel_uncertain: raise TimeoutError('cancel uncertain')
        for row in self.orders.values():
            if row['id']==key: row['status']='canceled'
    def positions(self): return []
    def open_orders(self): return [r for r in self.orders.values() if r['status'] not in ('filled','canceled','expired','rejected')]
    def activities(self,after): return []

class ExperimentsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.db=connect(Path(self.temp.name)/'state.db'); self.addCleanup(self.db.close); apply_migrations(self.db)
        self.market=evidence.connect(Path(self.temp.name)/'state.db.experiment-evidence.db'); self.addCleanup(self.market.close)
        self.broker=Broker()
        with self.db:
            self.db.execute('UPDATE execution_authority SET enabled=1')
            self.db.execute('INSERT INTO experiment_calendar VALUES (?,?,?,?,?)',('2026-10-14','2026-10-14T13:30:00Z','2026-10-14T20:00:00Z','2026-10-15',stamp(NOW)))
        p=preview(self.db,'stocks',self.broker,NOW); approve(self.db,p['id'],p['revision'],self.broker,NOW)
        self.batch=p['id']; self.instances={r['family']:r['id'] for r in self.db.execute('SELECT i.id,v.family FROM experiment_instances i JOIN experiment_versions v ON v.id=i.version_id')}
        self.instance=self.instances['trend']; self.meta=self.broker.preflight(['SPY'])['metadata']['SPY']; self.q={'ap':100,'bp':99.99}
    def buy(self): return reserve(self.db,self.instance,'SPY','buy',self.q,self.meta,NOW,'test',account_cash='1000')
    def row(self,key): return self.db.execute('SELECT * FROM experiment_orders WHERE id=?',(key,)).fetchone()
    def fill(self,key,qty=None,status='filled',at=NOW):
        request=json.loads(self.row(key)['request_json']); response={**request,'id':'broker-'+key,'status':status,'filled_qty':qty or request['qty'],'filled_avg_price':'100','updated_at':stamp(at)}
        apply_response(self.db,key,response,at); return response
    def test_frozen_preview_and_instance_budget(self):
        self.assertEqual(len(self.instances),5)
        self.assertEqual(sum(money(r[0]) for r in self.db.execute('SELECT budget FROM experiment_instances')),850)
        with self.assertRaises(Exception):
            self.db.execute("UPDATE experiment_versions SET config_json='{}'")
        self.db.rollback()
        with self.assertRaisesRegex(ValueError,'revision'): approve(self.db,self.batch,'bad',self.broker,NOW)
    def test_reserve_cap_and_same_symbol_serialization(self):
        key=self.buy(); self.assertLessEqual(money(self.row(key)['reserved']),50)
        with self.assertRaisesRegex(ValueError,'account/symbol'):
            reserve(self.db,self.instances['breakout'],'SPY','buy',self.q,self.meta,NOW,'test',account_cash='1000')
        self.assertGreater(available(self.db,self.instance),149)

    def test_approval_rejects_account_change_during_broker_preflight(self):
        with self.db: self.db.execute("UPDATE experiment_batches SET status='completed'")
        p=preview(self.db,'stocks',self.broker,NOW+timedelta(seconds=1))
        other=connect(Path(self.temp.name)/'state.db'); self.addCleanup(other.close)
        def account():
            # Another writer captures a cash activity after the approval has
            # snapshotted its ledger but before the broker reply returns.
            with other:
                other.execute("INSERT INTO broker_account_activities(broker,activity_id,activity_type,occurred_at,net_amount,captured_at,raw_json) VALUES ('alpaca-paper','concurrent-cash','DIV',?,1,?,'{}')",(stamp(NOW),stamp(NOW)))
            return {'id':'stocks-paper','cash':'1000','status':'ACTIVE','currency':'USD'}
        self.broker.account=account
        with self.assertRaisesRegex(ValueError,'ledger changed'):
            approve(self.db,p['id'],p['revision'],self.broker,NOW+timedelta(seconds=2))
        self.assertEqual(self.db.execute('SELECT status FROM experiment_batches WHERE id=?',(p['id'],)).fetchone()[0],'preview')
        self.assertEqual(self.db.execute('SELECT count(*) FROM experiment_instances WHERE batch_id=?',(p['id'],)).fetchone()[0],0)

    def test_pause_is_processed_without_waiting_for_a_preview(self):
        from stock_watch_worker.experiments.store import dispatch
        with self.db:
            self.db.execute("INSERT INTO experiment_commands(id,asset,action,payload_json,created) VALUES ('preview-pending','stocks','preview','{}',?)",(stamp(NOW-timedelta(seconds=1)),))
            self.db.execute("INSERT INTO experiment_commands(id,asset,action,payload_json,created) VALUES ('pause-now','stocks','pause',?,?)",(canonical({'batch_id':self.batch}),stamp(NOW)))
        # No broker object is needed: slow preview network work has its own queue.
        dispatch(self.db,'stocks',None,NOW,actions=('pause','resume','exit','exit_and_pause'))
        self.assertEqual(self.db.execute("SELECT status FROM experiment_commands WHERE id='pause-now'").fetchone()[0],'succeeded')
        self.assertEqual(self.db.execute("SELECT status FROM experiment_commands WHERE id='preview-pending'").fetchone()[0],'pending')
        self.assertTrue(all(r[0] for r in self.db.execute('SELECT paused FROM experiment_instances')))
    def test_timeout_never_reposts_or_releases(self):
        key=self.buy(); self.broker.timeout=True
        sync(self.db,self.broker,self.row(key),NOW)
        sync(self.db,self.broker,self.row(key),NOW+timedelta(minutes=2))
        self.assertEqual(self.broker.posts,1); self.assertEqual(self.row(key)['status'],'submitting')
        self.assertGreater(money(self.row(key)['reserved']),0)
    def test_partial_fill_is_delta_and_duplicate_is_idempotent(self):
        key=self.buy(); first=self.fill(key,'0.1','partially_filled'); apply_response(self.db,key,first,NOW)
        self.fill(key,'0.2','partially_filled')
        self.assertEqual(self.db.execute('SELECT count(*) FROM experiment_fills').fetchone()[0],2)
        self.assertEqual(money(position(self.db,self.instance,'SPY')['quantity']),money('.2'))
        self.assertEqual(money(self.db.execute('SELECT cash FROM experiment_instances WHERE id=?',(self.instance,)).fetchone()[0]),180)
    def test_cancel_race_holds_reserve(self):
        key=self.buy(); sync(self.db,self.broker,self.row(key),NOW)
        self.broker.cancel_uncertain=True; sync(self.db,self.broker,self.row(key),NOW+timedelta(seconds=61))
        self.assertEqual(self.row(key)['status'],'cancel_pending'); self.assertGreater(money(self.row(key)['reserved']),0)
    def test_settlement_uses_broker_date_not_next_trading_day(self):
        key=self.buy(); self.fill(key)
        sell=reserve(self.db,self.instance,'SPY','sell',self.q,self.meta,NOW,'exit'); self.fill(sell)
        self.assertLess(available(self.db,self.instance),200)
        release_settlement(self.db,NOW); self.assertLess(available(self.db,self.instance),200)
        release_settlement(self.db,NOW+timedelta(days=1)); self.assertEqual(available(self.db,self.instance),200)
    def test_missing_settlement_keeps_proceeds_unavailable(self):
        with self.db: self.db.execute('UPDATE experiment_calendar SET settlement_date=NULL')
        self.fill(self.buy()); sell=reserve(self.db,self.instance,'SPY','sell',self.q,self.meta,NOW,'exit'); self.fill(sell)
        release_settlement(self.db,NOW+timedelta(days=10)); self.assertLess(available(self.db,self.instance),200)
    def test_sell_cannot_exceed_owner_and_no_market_entry(self):
        with self.assertRaises(ValueError): reserve(self.db,self.instance,'SPY','sell',self.q,self.meta,NOW,'exit')
        with self.assertRaisesRegex(ValueError,'exit-only'): reserve(self.db,self.instance,'SPY','buy',self.q,self.meta,NOW,'entry',market=True)
    def test_market_fallback_only_remaining_quantity(self):
        self.fill(self.buy()); sell=reserve(self.db,self.instance,'SPY','sell',self.q,self.meta,NOW,'exit')
        self.fill(sell,'0.1','canceled')
        remaining=position(self.db,self.instance,'SPY')['quantity']
        market=reserve(self.db,self.instance,'SPY','sell',None,self.meta,NOW,'exit',market=True,parent=sell)
        self.assertEqual(money(json.loads(self.row(market)['request_json'])['qty']),money(remaining))
    def test_risk_resume_preserves_breach_and_highwater(self):
        with self.db: self.db.execute("UPDATE experiment_instances SET cash='100' WHERE id=?",(self.instance,))
        batch=self.db.execute('SELECT * FROM experiment_batches WHERE id=?',(self.batch,)).fetchone()
        self.assertEqual(valuation(self.db,batch,{},NOW),'pool_drawdown_limit')
        with self.assertRaisesRegex(ValueError,'Risk breach'): controls(self.db,{'batch_id':self.batch},'resume',NOW)
        self.assertEqual(self.db.execute('SELECT high_water FROM experiment_batches WHERE id=?',(self.batch,)).fetchone()[0],'1000')
    def test_tick_records_missing_data_and_does_not_replay_control(self):
        tick(self.db,self.market,self.broker,'stocks',NOW+timedelta(minutes=10))
        n=self.db.execute('SELECT count(*) FROM experiment_decisions').fetchone()[0]
        self.assertGreater(n,0); tick(self.db,self.market,self.broker,'stocks',NOW+timedelta(minutes=10))
        self.assertEqual(n,self.db.execute('SELECT count(*) FROM experiment_decisions').fetchone()[0]); self.assertEqual(self.broker.posts,0)
    def test_late_news_cannot_satisfy_earlier_decision(self):
        with self.market:
            self.market.execute('INSERT INTO news VALUES (?,?,?,?,?,?)',('1','a','SPY',stamp(NOW-timedelta(minutes=5)),stamp(NOW+timedelta(seconds=1)),'{}'))
        self.assertEqual(evidence.fresh_news(self.market,'SPY',NOW),[])
    def test_exact_251_bar_protocol_and_news_ablation(self):
        bars=[{'open':i+100,'high':i+100,'low':i+100,'close':i+100,'volume':1} for i in range(251)]
        self.assertEqual(signal(config('stocks','trend'),bars,False)[0],'buy')
        self.assertEqual(signal(config('stocks','trend'),bars[:-1],False)[1],'collecting')
        self.assertEqual(signal(config('stocks','news_breakout'),bars,False,False)[1],'waiting_news')
        self.assertEqual(signal(config('stocks','news_breakout'),bars,False,True)[0],'buy')

    def seed_bitcoin(self):
        broker=Broker('bitcoin'); p=preview(self.db,'bitcoin',broker,NOW-timedelta(minutes=1)); approve(self.db,p['id'],p['revision'],broker,NOW)
        close=NOW-timedelta(seconds=35)
        for index in range(251):
            at=close-timedelta(minutes=5*(250-index)); value=100+index
            evidence.put_bar(self.market,'bitcoin','alpaca-us','BTC/USD',stamp(at),stamp(at),
                {'open':value,'high':value,'low':value,'close':value,'volume':1},'stream')
        for offset in (0,5,65):
            at=NOW+timedelta(seconds=offset); q={'t':stamp(at),'bp':350,'ap':350.1,'bs':1,'as':1}
            with self.market: self.market.execute('INSERT INTO feed_events(asset,feed,symbol,kind,at,observed,payload) VALUES (?,?,?,?,?,?,?)',('bitcoin','alpaca-us','BTC/USD','q',stamp(at),stamp(at),canonical(q)))
        return broker,p

    def test_forward_signal_submits_one_owned_order_once_per_bar(self):
        broker,_=self.seed_bitcoin()
        tick(self.db,self.market,broker,'bitcoin',NOW)
        self.assertEqual(broker.posts,1)
        tick(self.db,self.market,broker,'bitcoin',NOW)
        self.assertEqual(broker.posts,1)
        self.assertGreater(self.db.execute("SELECT count(*) FROM experiment_decisions WHERE outcome='blocked'").fetchone()[0],0)

    def test_future_quote_is_never_used_in_a_replay(self):
        self.seed_bitcoin()
        q=evidence.quote(self.market,config('bitcoin','trend'),'BTC/USD',NOW)
        self.assertEqual(q['t'],stamp(NOW))
        with self.assertRaisesRegex(ValueError,'five seconds'):
            evidence.quote(self.market,config('bitcoin','trend'),'BTC/USD',NOW-timedelta(seconds=1))

    def test_replay_uses_engine_and_archives_complete_ledger(self):
        from stock_watch_worker.experiments.replay import execute
        _,p=self.seed_bitcoin()
        payload={'asset':'bitcoin','batch_id':p['id'],'start':stamp(NOW-timedelta(seconds=1)),'end':stamp(NOW+timedelta(seconds=70))}
        with self.db: self.db.execute("INSERT INTO workspace_jobs(id,kind,payload_json,created_at) VALUES ('replay-test','experiment_replay',?,?)",(canonical(payload),stamp(NOW)))
        job=self.db.execute("SELECT * FROM workspace_jobs WHERE id='replay-test'").fetchone()
        result=execute(self.db,job,Path(self.temp.name)/'state.db')
        self.assertEqual(result['ticks'],3)
        self.assertGreater(sum(r['fills'] for r in result['metrics']),0)
        self.assertEqual(sum(r['ranked'] for r in result['metrics']),4)
        for artifact in result['artifacts'].values(): self.assertTrue((Path(self.temp.name)/'state.db.systems-data'/artifact).is_file())

    def test_daily_digest_cutoff_catches_a_missed_minute(self):
        from stock_watch_worker.experiments.reporting import due_cutoff, projection, message
        after=datetime(2026,10,15,1,7,tzinfo=timezone.utc)
        cutoff=due_cutoff(after.timestamp(),'20:00')
        self.assertEqual(cutoff.hour,20); self.assertEqual(cutoff.day,14)
        self.fill(self.buy())
        report=projection(self.db,None,NOW-timedelta(hours=1),NOW+timedelta(hours=1))
        text=message(report); self.assertIn('Stocks: 1 buys',text)
        self.assertEqual(next(r for r in report['groups'] if r['group']=='experiments' and r['asset']=='stocks')['filled_orders'],1)

    def test_weekly_proposals_are_bounded_and_do_not_activate(self):
        from stock_watch_worker.experiments.research import propose
        propose(self.db,NOW); propose(self.db,NOW+timedelta(days=1))
        self.assertEqual(self.db.execute('SELECT count(*) FROM experiment_research_proposals').fetchone()[0],16)
        self.assertEqual(self.db.execute("SELECT count(*) FROM experiment_batches WHERE approved IS NOT NULL").fetchone()[0],1)

    def test_settlement_calendar_observes_bank_holiday_with_stock_trading(self):
        from stock_watch_worker.experiments.collector import calendar
        class CalendarBroker:
            def calendar(self,start,end,date_type='TRADING'):
                if date_type=='SETTLEMENT': return [{'date':d} for d in ('2026-10-09','2026-10-13','2026-10-14')]
                return [{'date':d,'open':'09:30','close':'16:00'} for d in ('2026-10-09','2026-10-12','2026-10-13')]
        calendar(self.db,CalendarBroker(),NOW)
        self.assertEqual(self.db.execute("SELECT settlement_date FROM experiment_calendar WHERE date='2026-10-09'").fetchone()[0],'2026-10-13')
        self.assertEqual(self.db.execute("SELECT settlement_date FROM experiment_calendar WHERE date='2026-10-12'").fetchone()[0],'2026-10-13')

    def test_fee_outage_does_not_stop_an_owned_deadline_exit(self):
        key=self.buy(); self.fill(key); own=position(self.db,self.instance,'SPY')
        self.broker.positions=lambda:[{'symbol':'SPY','qty':own['quantity']}]
        def failed(after): raise TimeoutError('fee service unavailable')
        self.broker.activities=failed
        now=NOW+timedelta(hours=2,seconds=5)
        q={'t':stamp(now),'ap':100,'bp':99.99}
        with self.market: self.market.execute('INSERT INTO feed_events(asset,feed,symbol,kind,at,observed,payload) VALUES (?,?,?,?,?,?,?)',('stocks','iex','SPY','q',stamp(now),stamp(now),canonical(q)))
        tick(self.db,self.market,self.broker,'stocks',now)
        self.assertEqual(self.broker.posts,1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM experiment_orders WHERE side='sell'").fetchone()[0],1)
        self.assertIsNotNone(self.db.execute("SELECT error FROM experiment_health WHERE component='fees:stocks'").fetchone()[0])
        self.broker.activities=lambda after:[]
        tick(self.db,self.market,self.broker,'stocks',now+timedelta(seconds=1))
        self.assertIsNone(self.db.execute("SELECT error FROM experiment_health WHERE component='fees:stocks'").fetchone()[0])

    def test_daily_aggregate_fees_use_complete_fill_weights_once(self):
        from stock_watch_worker.experiments.fees import capture
        broker,p=self.seed_bitcoin(); instances=[r[0] for r in self.db.execute('SELECT id FROM experiment_instances WHERE batch_id=?',(p['id'],))][:2]
        events=[]; gross=money(0)
        for instance in instances:
            key=reserve(self.db,instance,'BTC/USD','buy',{'ap':100,'bp':99.99},self.meta,NOW,'test',account_cash='1000')
            response=self.fill(key); quantity=money(response['filled_qty']); gross+=quantity
            events.append({'activity_type':'FILL','id':'f-'+key,'order_id':response['id'],'transaction_time':stamp(NOW),'side':'buy','qty':str(quantity),'price':'100'})
        fee=gross*money('.0025')
        events.append({'activity_type':'CFEE','id':'aggregate-fee','date':NOW.date().isoformat(),'symbol':'BTC','qty':str(fee),'net_amount':'0'})
        broker.activities=lambda after:events
        batch=self.db.execute('SELECT * FROM experiment_batches WHERE id=?',(p['id'],)).fetchone()
        self.assertTrue(capture(self.db,broker,batch,NOW+timedelta(days=1)))
        self.assertTrue(capture(self.db,broker,batch,NOW+timedelta(days=1)))
        net=sum((money(r[0]) for r in self.db.execute("SELECT p.quantity FROM experiment_positions p JOIN experiment_instances i ON i.id=p.instance_id WHERE i.batch_id=?",(p['id'],))),money(0))
        self.assertEqual(net,gross-fee);self.assertEqual(self.db.execute('SELECT count(*) FROM experiment_fees').fetchone()[0],2)

    def test_pausing_cancels_a_known_order_and_preserves_uncertainty(self):
        key=self.buy();sync(self.db,self.broker,self.row(key),NOW)
        controls(self.db,{'instance_id':self.instance},'pause',NOW)
        sync(self.db,self.broker,self.row(key),NOW,force_cancel=True)
        self.assertEqual(self.row(key)['status'],'canceled')

    def test_aggregate_fee_waits_for_missing_legacy_fill_evidence(self):
        from stock_watch_worker.experiments.fees import capture
        from stock_watch_worker.systems.research import register_version
        from stock_watch_worker.systems.automation_config import BitcoinConfig
        broker,p=self.seed_bitcoin()
        instance=self.db.execute('SELECT id FROM experiment_instances WHERE batch_id=? LIMIT 1',(p['id'],)).fetchone()[0]
        key=reserve(self.db,instance,'BTC/USD','buy',self.q,self.meta,NOW,'test',account_cash='1000'); response=self.fill(key)
        version=register_version(self.db,BitcoinConfig('bitcoin'))
        with self.db:
            self.db.execute("INSERT INTO btc_accounts(id,created_at) VALUES ('bitcoin-paper',?)",(stamp(NOW),))
            self.db.execute("INSERT INTO btc_orders(id,version_id,account_id,side,quantity,filled_qty,filled_notional,broker_id,status,reference_price,created_at,updated_at,reason) VALUES ('old-order',?,'bitcoin-paper','buy','.1','.1','10','old-broker-order','filled','100',?,?,'test')",(version,stamp(NOW),stamp(NOW)))
        fee=(money(response['filled_qty'])+money('.1'))*money('.0025')
        events=[{'activity_type':'FILL','id':'new-fill','order_id':response['id'],'transaction_time':stamp(NOW),'side':'buy','qty':response['filled_qty'],'price':'100'},
            {'activity_type':'CFEE','id':'shared-fee','date':NOW.date().isoformat(),'symbol':'BTC','qty':str(fee),'net_amount':'0'}]
        broker.activities=lambda after:events
        batch=self.db.execute('SELECT * FROM experiment_batches WHERE id=?',(p['id'],)).fetchone()
        self.assertFalse(capture(self.db,broker,batch,NOW+timedelta(days=1)))
        self.assertEqual(self.db.execute('SELECT count(*) FROM experiment_fees').fetchone()[0],0)
        events.append({'activity_type':'FILL','id':'old-fill','order_id':'old-broker-order','transaction_time':stamp(NOW),'side':'buy','qty':'.1','price':'100'})
        self.assertTrue(capture(self.db,broker,batch,NOW+timedelta(days=1)))
        self.assertEqual(money(self.db.execute('SELECT quantity FROM experiment_fees').fetchone()[0]),money(response['filled_qty'])*money('.0025'))
        self.assertEqual(money(self.db.execute('SELECT quantity_fee FROM btc_fee_allocations').fetchone()[0]),money('.00025'))

    def test_primary_source_context_parser_is_bounded_and_links_official_sources(self):
        from stock_watch_worker.experiments.context import parse
        raw=b'<rss><channel><item><title>Employment report</title><link>https://www.bls.gov/news.release/empsit.nr0.htm</link><pubDate>Wed, 14 Oct 2026 08:30:00 -0400</pubDate></item></channel></rss>'
        rows=parse(raw,'BLS employment',NOW);self.assertEqual(len(rows),1);self.assertEqual(rows[0][1],'BLS employment')
        with self.assertRaises(ValueError): parse(b'<!DOCTYPE x>'+raw,'BLS',NOW)

    def test_sec_context_refresh_tolerates_a_concurrent_writer(self):
        from unittest.mock import patch
        from stock_watch_worker.experiments import context
        other=connect(Path(self.temp.name)/'state.db'); self.addCleanup(other.close)
        with self.db:
            for symbol in ('AAPL','MSFT'):
                document={'observedAt':stamp(NOW),'filings':[{
                    'accession':symbol+'-filing','form':'10-Q','accepted':stamp(NOW),
                    'url':'https://www.sec.gov/Archives/'+symbol,
                }]}
                self.db.execute("INSERT INTO company_context(symbol,status,requested_at,payload_json) VALUES (?,'ready',?,?)",
                    (symbol,stamp(NOW),canonical(document)))
        loads=json.loads
        writes=[]
        def concurrent_write(raw):
            # An execution/collection writer can commit after the SEC read
            # begins but before its first display-projection insert.
            with other:
                other.execute('UPDATE experiment_stock_revision SET revision=revision+1 WHERE id=1')
            writes.append(True)
            return loads(raw)
        with patch.dict(context.FEEDS,{},clear=True), patch.object(context.json,'loads',side_effect=concurrent_write):
            context.collect(self.db,NOW)
            context.collect(self.db,NOW+timedelta(minutes=1))
        self.assertEqual(len(writes),4)
        rows=self.db.execute("SELECT symbol FROM experiment_context WHERE source='SEC EDGAR' ORDER BY symbol").fetchall()
        self.assertEqual([r['symbol'] for r in rows],['AAPL','MSFT'])
        self.assertFalse(self.db.in_transaction)

    def test_crypto_fee_reserve_does_not_prevent_the_next_entry(self):
        broker,p=self.seed_bitcoin()
        instance=self.db.execute("SELECT i.id FROM experiment_instances i JOIN experiment_versions v ON v.id=i.version_id WHERE i.batch_id=? AND v.family='trend'",(p['id'],)).fetchone()[0]
        key=reserve(self.db,instance,'BTC/USD','buy',self.q,self.meta,NOW,'test',account_cash='1000'); response=self.fill(key)
        self.assertEqual(money(position(self.db,instance,'BTC/USD')['quantity']),money(response['filled_qty'])*money('.9975'))
        sell=reserve(self.db,instance,'BTC/USD','sell',self.q,self.meta,NOW,'test');self.fill(sell)
        # Any remaining quantity is below the broker increment, rather than a
        # fictitious open position equal to the entire pending fee reserve.
        self.assertLess(money(position(self.db,instance,'BTC/USD')['quantity']),money(self.meta['minimum_quantity']))
        another=reserve(self.db,instance,'BTC/USD','buy',self.q,self.meta,NOW+timedelta(minutes=31),'test',account_cash='1000')
        self.assertTrue(another)

    def test_legacy_bitcoin_reconciliation_accepts_pending_experiment_sell_fee(self):
        from stock_watch_worker.systems.coordinator import reconcile
        broker,p=self.seed_bitcoin()
        instance=self.db.execute('SELECT id FROM experiment_instances WHERE batch_id=? LIMIT 1',(p['id'],)).fetchone()[0]
        buy=reserve(self.db,instance,'BTC/USD','buy',self.q,self.meta,NOW,'test',account_cash='1000'); self.fill(buy)
        sell=reserve(self.db,instance,'BTC/USD','sell',self.q,self.meta,NOW,'test');self.fill(sell)
        cash=money(1000)-money(self.row(buy)['filled_notional'])+money(self.row(sell)['filled_notional'])*money('.9975')
        with self.db: self.db.execute("INSERT INTO btc_accounts(id,initial_cash,cash,created_at) VALUES ('bitcoin-paper','1000','1000',?)",(stamp(NOW),))
        broker.fills=lambda after:[]; broker.fees=lambda after:[]
        account={'id':'bitcoin-paper','cash':str(cash)}
        self.assertTrue(reconcile(self.db,broker,account,NOW))
        # Unexplained debits remain blocked after the bounded fee posting window.
        self.assertFalse(reconcile(self.db,broker,account,NOW+timedelta(hours=49)))

    def test_released_fee_reserve_is_not_recharged_on_next_poll(self):
        from stock_watch_worker.experiments.fees import reconcile_provisions
        broker,p=self.seed_bitcoin()
        instance=self.db.execute('SELECT id FROM experiment_instances WHERE batch_id=? LIMIT 1',(p['id'],)).fetchone()[0]
        key=reserve(self.db,instance,'BTC/USD','buy',self.q,self.meta,NOW,'test',account_cash='1000'); response=self.fill(key)
        batch=self.db.execute('SELECT * FROM experiment_batches WHERE id=?',(p['id'],)).fetchone()
        later=NOW+timedelta(hours=49)
        reconcile_provisions(self.db,batch,later,settled=True);reconcile_provisions(self.db,batch,later+timedelta(seconds=5))
        self.assertEqual(money(position(self.db,instance,'BTC/USD')['quantity']),money(response['filled_qty']))

if __name__=='__main__': unittest.main()
