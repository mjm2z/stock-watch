"""Execution safety for the browser-visible order types. No network or paper orders."""
import json
import unittest
from decimal import Decimal
import test_manual_paper as manual_fixture
from stock_watch_worker.manual.execution import reconcile


class OrderTypes(unittest.TestCase):
    setUp = manual_fixture.ManualTests.setUp
    tearDown = manual_fixture.ManualTests.tearDown
    preview = manual_fixture.ManualTests.preview
    confirm = manual_fixture.ManualTests.confirm
    setup_account = manual_fixture.ManualTests.setup_account

    def setUp(self):
        manual_fixture.ManualTests.setUp(self)
        broker = self.brokers['stocks']
        old_metadata = broker.metadata
        broker.metadata = lambda symbol: {**old_metadata(symbol), 'fractionable': True}
        self.setup_account()

    def market(self, **changes):
        return self.preview(dict(action='order', asset='stocks', symbol='SPY', side='buy',
                                 order_type='market', notional='50', **changes))

    def test_notional_partial_fill_reservation_and_no_invented_price(self):
        identity = self.confirm(self.market())['instruction']
        row = self.db.execute('SELECT * FROM instructions').fetchone()
        request = json.loads(row['request'])
        self.assertEqual(request['notional'], '50')
        self.assertNotIn('qty', request)
        self.assertNotIn('limit_price', request)
        reconcile(self.manual)
        self.brokers['stocks'].orders[identity].update(status='partially_filled', filled_qty='0.05', filled_avg_price='600')
        reconcile(self.manual)
        row = self.db.execute('SELECT * FROM instructions').fetchone()
        self.assertEqual(Decimal(row['reserved_cash']), Decimal('20.20'))
        reconcile(self.manual)
        self.assertEqual(self.brokers['stocks'].posts, 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fills').fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM activity WHERE kind='fill'").fetchone()[0], 1)

    def test_market_fee_cap_session_and_fractionability(self):
        with self.assertRaisesRegex(ValueError, 'entry cap'):
            self.preview(dict(action='order', asset='stocks', symbol='SPY', side='buy', order_type='market', notional='100'))
        self.brokers['stocks'].market_open = lambda: False
        with self.assertRaisesRegex(ValueError, 'regular session'):
            self.market()
        self.brokers['stocks'].market_open = lambda: True
        self.brokers['stocks'].metadata = lambda _: {'tradable': True, 'class': 'us_equity', 'fractionable': False}
        with self.assertRaisesRegex(ValueError, 'fractionable'):
            self.market()

    def test_fractional_day_limit_and_reject_crypto_stop(self):
        command = dict(action='order', asset='stocks', symbol='SPY', side='buy', qty='0.1', limit='600')
        self.confirm(self.preview(command))
        with self.assertRaisesRegex(ValueError, 'DAY'):
            self.preview({**command, 'time_in_force': 'gtc'})
        with self.assertRaisesRegex(ValueError, 'Unsupported order type'):
            self.preview(dict(action='order', asset='bitcoin', symbol='BTC/USD', side='sell', qty='0.1', order_type='stop', stop_price='60000'))

    def test_network_outside_lock_and_concurrent_change_rejects_confirmation(self):
        draft = self.market()
        broker = self.brokers['stocks']
        original = broker.quote
        def changing_quote(symbol):
            self.assertFalse(self.db.in_transaction)
            self.db.execute("UPDATE accounts SET budget='999' WHERE asset='stocks'")
            self.db.commit()
            return original(symbol)
        broker.quote = changing_quote
        with self.assertRaisesRegex(ValueError, 'state changed'):
            self.confirm(draft)
        self.assertEqual(self.db.execute('SELECT count(*) FROM instructions').fetchone()[0], 0)

    def test_fractional_protection_sizes_actual_market_fills_with_day(self):
        identity = self.confirm(self.market())['instruction']
        reconcile(self.manual)
        broker = self.brokers['stocks']
        broker.orders[identity].update(status='filled',filled_qty='0.05',filled_avg_price='1000')
        broker.position_state = [{'symbol':'SPY','qty':'0.05'}]
        broker.open_orders = lambda: []
        reconcile(self.manual)
        self.confirm(self.preview(dict(action='protect',asset='stocks',instruction=identity,stop_loss='11')))
        reconcile(self.manual)
        child = self.db.execute("SELECT * FROM instructions WHERE side='sell'").fetchone()
        self.assertIsNotNone(child)
        request = json.loads(child['request'])
        self.assertEqual(Decimal(request['qty']),Decimal('0.05'))
        self.assertEqual(request['time_in_force'],'day')
        self.assertIsNone(child['expires'])

    def test_market_closed_between_confirmation_and_dispatch_releases_reserve_without_post(self):
        self.confirm(self.market())
        self.brokers['stocks'].market_open = lambda: False
        reconcile(self.manual)
        row = self.db.execute('SELECT * FROM instructions').fetchone()
        self.assertEqual(row['status'],'rejected')
        self.assertEqual(row['reserved_cash'],'0')
        self.assertEqual(self.brokers['stocks'].posts,0)

    def test_allocation_returns_use_thousand_dollar_sleeve_and_identified_fees(self):
        from stock_watch_worker.manual.accounting import allocation_performance
        self.confirm(self.market())
        self.db.execute("UPDATE instructions SET filled_qty='0.05',filled_notional='50',status='filled',reserved_cash='0'")
        self.db.commit()
        positions=[{'symbol':'SPY','qty':'0.05','market_value':'55'}]
        result=allocation_performance(self.manual,self.brokers['stocks'].account(),positions,{'cash_reconciled':True})
        stocks=next(r for r in result if r['asset']=='stocks')
        bitcoin=next(r for r in result if r['asset']=='bitcoin')
        self.assertEqual(stocks['equity'],'1005')
        self.assertEqual(stocks['net_return'],0.005)
        self.assertEqual(bitcoin['net_return'],0)
        self.db.execute('INSERT INTO fee_activities VALUES (?,?,?,?)',('manual-paper','fee',json.dumps({'id':'fee','net_amount':'-1'}),self.now))
        self.db.commit()
        result=allocation_performance(self.manual,self.brokers['stocks'].account(),positions,{'cash_reconciled':True})
        self.assertTrue(all(r['net_return'] is None for r in result))
