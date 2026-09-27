from pathlib import Path
import sqlite3
import unittest
from stock_watch_worker.stock_prerequisites import stock_prerequisites, require_stock_inputs

START, END = '2026-01-01T00:00:00Z', '2026-01-06T00:00:00Z'


class StockPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        fixture = Path(__file__).resolve().parents[2] / 'tests/fixtures/stock-prerequisites.sql'
        self.db.executescript(fixture.read_text())

    def tearDown(self):
        self.db.close()

    def raw(self, provider='alpaca'):
        self.db.execute("INSERT INTO market_bars VALUES (1,'2026-01-02T05:00:00Z','1Day','raw',?)", (provider,))

    def test_adjusted_only_history_is_not_raw_and_read_does_not_write(self):
        before = self.db.total_changes
        report = stock_prerequisites(self.db, START, END)
        self.assertFalse(report['canPrepare'])
        self.assertEqual(report['rawBars'], 0)
        self.assertEqual(report['requestedSessions'], 2)
        self.assertEqual(self.db.total_changes, before)
        with self.assertRaisesRegex(ValueError, 'Raw daily bars are missing'):
            require_stock_inputs(self.db, START, END)

    def test_partial_inputs_are_disclosed_without_claiming_qualification(self):
        self.raw()
        report = stock_prerequisites(self.db, START, END)
        self.assertTrue(report['canPrepare'])
        self.assertEqual((report['instruments'],report['usableInstruments'],report['missingSectors']), (2,1,1))
        self.assertEqual(report['benchmarkBars'], 0)
        self.assertEqual(report['coveredEnd'], '2026-01-02T21:00:00Z')
        self.assertNotIn('qualified', report)
        self.assertFalse(report['quality']['assessmentReady'])
        self.assertEqual(len(report['quality']['assessmentBlockers']), 2)

    def test_requested_interval_excludes_later_bars_and_requires_calendar(self):
        self.raw()
        self.assertFalse(stock_prerequisites(self.db, START, '2026-01-02T21:00:00Z')['canPrepare'])
        self.assertTrue(stock_prerequisites(self.db, '2026-01-02T21:00:00Z', END)['canPrepare'])
        self.db.execute('DELETE FROM market_sessions')
        report = stock_prerequisites(self.db, START, END)
        self.assertFalse(report['canPrepare'])
        self.assertEqual(report['barsWithoutCalendar'], 1)

    def test_ambiguous_providers_and_missing_sectors_block(self):
        self.raw()
        self.raw('other')
        report = stock_prerequisites(self.db, START, END)
        self.assertFalse(report['canPrepare'])
        self.assertEqual(report['ambiguousSessions'], 1)
        self.db.execute('DELETE FROM instrument_context')
        self.assertIn('Sector metadata is missing for all universe members', stock_prerequisites(self.db, START, END)['blockers'])
