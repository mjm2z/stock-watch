import json
import sqlite3
import unittest
from pathlib import Path
from stock_watch_worker.database import apply_migrations
from stock_watch_worker.performance import link, record_mark
from stock_watch_worker.ingestion import persist_market_bars
from stock_watch_worker.providers.alpaca import MarketBar


def mark(equity, flow=0, **details):
    return {'equity':str(equity),'external_flow':str(flow),'flow_coverage':1,
            'valuation_complete':1,'details_json':json.dumps(details)}


class PerformanceTests(unittest.TestCase):
    def test_deposits_and_withdrawals_do_not_create_return(self):
        initial=mark(100)
        for equity,flow in ((150,50),(60,-40)):
            result=link(initial,mark(equity,flow,flow_events=1,flow_timing='end_at_valuation'))
            self.assertEqual(result['return'],0)
            self.assertEqual(result['maximum_drawdown'],0)

    def test_cash_flow_without_event_valuation_is_unavailable(self):
        self.assertFalse(link(mark(100),mark(150,50))['available'])
        self.assertFalse(link(mark(100),mark(100,0,flow_events=2))['available'])

    def test_internal_transfer_changes_neither_total_equity_nor_return(self):
        self.assertEqual(link(mark(100),mark(100,internal_transfer=50))['return'],0)

    def test_drawdown_uses_return_index_and_preserves_trough(self):
        up=link(mark(100),mark(120))
        down=link(mark(120),mark(90),up)
        recovered=link(mark(90),mark(120),down)
        self.assertAlmostEqual(recovered['return'],.2)
        self.assertAlmostEqual(recovered['maximum_drawdown'],-.25)

    def test_unknown_coverage_and_zero_start_are_not_zero_return(self):
        self.assertFalse(link(mark(0),mark(20))['available'])
        incomplete={**mark(100),'flow_coverage':0}
        broken=link(mark(100),incomplete)
        self.assertIsNone(broken['return'])
        self.assertFalse(link(mark(100),mark(110),broken)['available'])

    def test_measurement_is_idempotent_and_scope_specific(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        apply_migrations(db)
        opts=dict(scope='stocks_account',owner='paper',cash='100',flow_coverage=True,valuation_complete=True)
        record_mark(db,at='2026-01-01',equity='100',**opts)
        record_mark(db,at='2026-01-02',equity='110',**opts)
        record_mark(db,at='2026-01-02',equity='999',**opts)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM performance_marks').fetchone()[0],2)
        result=json.loads(db.execute('SELECT payload_json FROM performance_results').fetchone()[0])
        self.assertAlmostEqual(result['return'],.1)
        self.assertEqual(result['scope'],'stocks_account')
        db.close()


class FeedTests(unittest.TestCase):
    def test_consolidated_feed_never_overwrites_legacy_iex_volume(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        apply_migrations(db)
        db.execute("INSERT INTO instruments(symbol,name) VALUES ('AAPL','Apple')")
        options=dict(timeframe='1Day',adjustment='all',provider='alpaca')
        iex=MarketBar('AAPL','2026-01-01T05:00:00Z',100,105,95,101,1000,None,None)
        sip=MarketBar('AAPL','2026-01-01T05:00:00Z',100,105,95,101,100000,None,None)
        persist_market_bars(db,[iex],feed='iex',**options)
        persist_market_bars(db,[sip],feed='sip',**options)
        repeated=persist_market_bars(db,[sip],feed='sip',**options)
        self.assertEqual(repeated.unchanged,1)
        self.assertEqual(db.execute('SELECT volume FROM market_bars').fetchone()[0],1000)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM market_series').fetchone()[0],2)
        db.close()


class FundamentalReviewTests(unittest.TestCase):
    def test_date_only_filing_waits_for_next_exchange_open(self):
        from stock_watch_worker.fundamental_review import available
        e={'filed':'2026-01-02'}
        sessions=[('2026-01-05','2026-01-05T14:30:00Z')]
        self.assertFalse(available(e,'2026-01-02T20:00:00Z',sessions))
        self.assertFalse(available(e,'2026-01-05T14:29:00Z',sessions))
        self.assertTrue(available(e,'2026-01-05T14:30:00Z',sessions))

    def test_ttm_differences_ytd_without_double_counting_and_freezes_future_revision(self):
        from stock_watch_worker.fundamental_review import ttm
        entries=[{'start':'2025-01-01','end':end,'val':v,'filed':'2026-01-02',
                  'form':form,'accn':end} for end,v,form in [
                  ('2025-03-31',10,'10-Q'),('2025-06-30',25,'10-Q'),
                  ('2025-09-30',45,'10-Q'),('2025-12-31',70,'10-K')]]
        sessions=[('2026-01-05','2026-01-05T14:30:00Z')]
        original=ttm(entries,'2026-01-05T15:00:00Z',sessions)
        self.assertTrue(original['available'])
        self.assertEqual(original['value'],70)
        self.assertEqual([q['value'] for q in original['quarters']],[10,15,20,25])
        entries.append({**entries[-1],'filed':'2026-05-01','val':999})
        self.assertEqual(ttm(entries,'2026-01-05T15:00:00Z',sessions),original)


if __name__ == "__main__":
    unittest.main()
