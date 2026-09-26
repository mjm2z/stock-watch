import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import asdict
from unittest.mock import patch
from stock_watch_worker.database import connect,apply_migrations
from stock_watch_worker.systems.rules import RuleConfig,operand,position_exit
from stock_watch_worker.systems.engine import decision,replay,canonical,SystemConfig
from stock_watch_worker.systems.workspace import run_workspace
from test_systems import dataset


def group(op='gt',left=None,right=None):
    return {'op':'all','conditions':[{'op':op,'left':left or {'kind':'close'},'right':right or {'kind':'number','value':100}}]}

class VisualRuleTests(unittest.TestCase):
    def config(self,**kwargs):return RuleConfig('bitcoin',group(),group('lt'),timeframe='1Hour',**kwargs)
    def test_rule_decisions_and_insufficient_volume(self):
        c=self.config();rows=dataset([99,101])['bars']
        self.assertEqual(decision(c,rows,False)[0],'buy')
        self.assertEqual(decision(c,rows,True)[0],'hold')
        c=RuleConfig('stocks',group(left={'kind':'average_volume','period':2}),group())
        self.assertEqual(decision(c,rows,False)[0],'hold')
    def test_crossovers_prior_highs_and_recursive_warmup(self):
        rows=dataset([99,101])['bars']
        c=RuleConfig('bitcoin',group('crosses_above'),group())
        self.assertEqual(decision(c,rows,False)[0],'buy')
        self.assertEqual(decision(c,rows+dataset([102])['bars'],False)[0],'hold')
        self.assertEqual(operand({'kind':'prior_high','period':2},dataset([90,100,150])['bars']),100)
        rows=dataset(list(range(1,301)))['bars']
        c=RuleConfig('bitcoin',group(left={'kind':'ema','period':20}),group())
        self.assertEqual(decision(c,rows,False),decision(c,rows[-251:],False))
    def test_invalid_rules_depth_and_nan(self):
        for g in [{'op':'all','conditions':[None]}, {'op':'all','conditions':[{'op':'all','conditions':[group()]}]},group(right={'kind':'number','value':float('nan')})]:
            with self.assertRaises(ValueError):RuleConfig('bitcoin',g,group())
        with self.assertRaises(ValueError):self.config(allocation=.6)
        with self.assertRaises(ValueError):self.config(holding_count=13,holding_unit='months')
    def test_risk_limits_act_in_replay_and_preserve_legacy_hash(self):
        c=self.config(stop_loss=.03,take_profit=.05,holding_count=12,holding_unit='months')
        result=replay(c,dataset([101,110,90,80]))
        self.assertTrue(any(f['side']=='sell' and 'profit' in f['reason'] for f in result['fills']))
        self.assertEqual(position_exit(c,90,100,None,'2026-01-01T00:00:00Z'),'System stop loss')
        self.assertEqual(SystemConfig('bitcoin').sha256,'e664521e08effecaea9a67e44b54ccf858675184860ad186493eb0e8f4a5856d')

class WorkspaceJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'app.db';self.db=connect(self.path);apply_migrations(self.db)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def enqueue(self,kind,body,id='job'):
        with self.db:self.db.execute('INSERT INTO workspace_jobs(id,kind,payload_json,created_at) VALUES (?,?,?,?)',(id,kind,canonical(body),'2026-01-01T00:00:00Z'))
    def test_unenrolled_collector_needs_no_broker_credentials(self):
        from stock_watch_worker.systems.cli import main
        with patch('stock_watch_worker.systems.cli.CryptoBroker') as broker:
            main(['--database',str(self.path),'automation-data'])
            broker.assert_not_called()

    def test_publish_is_frozen_and_preserves_draft_and_version(self):
        doc=asdict(RuleConfig('stocks',group(),group('lt')))
        with self.db:self.db.execute('INSERT INTO workspace_drafts(id,name,asset,document_json,updated_at) VALUES (?,?,?,?,?)',('draft','Edited later','stocks','{}','now'))
        self.enqueue('publish',{'asset':'stocks','draft':'draft','snapshot':{'name':'Frozen name','document_json':canonical(doc)}})
        run_workspace(self.db,self.path)
        row=self.db.execute('SELECT * FROM system_versions').fetchone()
        self.assertEqual(row['hypothesis'],'Frozen name');self.assertEqual(json.loads(row['config_json']),doc)
        self.assertEqual(self.db.execute('SELECT status FROM workspace_jobs').fetchone()[0],'succeeded')
        run_workspace(self.db,self.path)
        self.assertEqual(self.db.execute('SELECT count(*) FROM system_versions').fetchone()[0],1)
    def test_failed_or_canceled_job_never_publishes(self):
        self.enqueue('publish',{'asset':'stocks','draft':'missing'})
        run_workspace(self.db,self.path)
        self.assertEqual(self.db.execute('SELECT status FROM workspace_jobs').fetchone()[0],'failed')
        self.assertEqual(self.db.execute('SELECT count(*) FROM system_versions').fetchone()[0],0)

class MigrationPreservationTests(unittest.TestCase):
    def test_existing_orders_keep_authority_but_funding_alone_does_not(self):
        import sqlite3
        from stock_watch_worker.systems.research import register_version
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        migrations=Path(__file__).parents[1]/'migrations'
        for name in ('016_systems','017_bitcoin_automation'):db.executescript((migrations/(name+'.sql')).read_text())
        old=register_version(db,SystemConfig('bitcoin','trend'),'Original hypothesis')
        funded=register_version(db,SystemConfig('bitcoin','breakout'),'Untouched idea')
        db.execute("INSERT INTO btc_accounts(id,created_at) VALUES ('account','old-date')")
        for version in (old,funded):db.execute("INSERT INTO btc_allocations(version_id,account_id,budget,cash,high_water,approved_at) VALUES (?,'account','150','150','150','old-date')",(version,))
        db.execute("INSERT INTO btc_orders(id,version_id,account_id,side,quantity,reference_price,created_at,updated_at,reason) VALUES ('original-order',?,'account','buy','0.01','50000','original-date','original-date','Original reason')",(old,))
        before=dict(db.execute('SELECT * FROM btc_orders').fetchone())
        versions=[dict(r) for r in db.execute('SELECT * FROM system_versions')]
        db.executescript((migrations/'018_workspace.sql').read_text())
        self.assertEqual(before,dict(db.execute('SELECT * FROM btc_orders').fetchone()))
        self.assertEqual(versions,[dict(r) for r in db.execute('SELECT * FROM system_versions')])
        self.assertEqual(db.execute('SELECT started_at FROM btc_allocations WHERE version_id=?',(old,)).fetchone()[0],'original-date')
        self.assertIsNone(db.execute('SELECT started_at FROM btc_allocations WHERE version_id=?',(funded,)).fetchone()[0])
        db.close()

class ChartPaginationTests(unittest.TestCase):
    def payload(self):return {'frame':'1Hour','start':'2026-08-27T00:00:00Z','end':'2026-09-26T00:00:00Z'}
    def bar(self,day):return {'t':f'2026-09-{day:02}T00:00:00Z','o':100,'h':110,'l':90,'c':105,'v':1}
    def fetch(self,transport):
        from stock_watch_worker.systems.workspace import chart
        with patch.dict('os.environ',{'ALPACA_API_KEY_ID':'fixture','ALPACA_API_SECRET_KEY':'fixture'},clear=True):return chart(self.payload(),transport)
    def test_follows_pages_deduplicates_and_finishes_requested_history(self):
        from fakes import FakeTransport,json_response
        transport=FakeTransport(json_response({'bars':{'BTC/USD':[self.bar(1)]},'next_page_token':'next'}),json_response({'bars':{'BTC/USD':[self.bar(1),self.bar(25)]},'next_page_token':None}))
        result=self.fetch(transport)
        self.assertEqual(len(result['bars']),2)
        self.assertEqual(result['coverageEnd'],'2026-09-25T00:00:00Z')
        self.assertFalse(result['partial'])
        self.assertIn('page_token=next',transport.requests[1].url)
    def test_repeated_page_token_cannot_loop(self):
        from fakes import FakeTransport,json_response
        page={'bars':{'BTC/USD':[self.bar(1)]},'next_page_token':'same'}
        with self.assertRaisesRegex(ValueError,'pagination token'):self.fetch(FakeTransport(json_response(page),json_response(page)))
    def test_page_limit_remains_explicitly_partial(self):
        from fakes import FakeTransport,json_response
        transport=FakeTransport(*[json_response({'bars':{'BTC/USD':[self.bar(1)]},'next_page_token':str(i)}) for i in range(40)])
        self.assertTrue(self.fetch(transport)['partial'])
        self.assertEqual(len(transport.requests),40)
