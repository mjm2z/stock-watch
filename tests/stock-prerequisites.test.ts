jest.mock('server-only', () => ({}))
import { DatabaseSync } from 'node:sqlite'
import { readFileSync } from 'node:fs'
import { stockPrerequisites } from '@/lib/stock-prerequisites'

const start = '2026-01-01T00:00:00Z',
  end = '2026-01-06T00:00:00Z'
let db: DatabaseSync
beforeEach(() => {
  db = new DatabaseSync(':memory:')
  db.exec(readFileSync('tests/fixtures/stock-prerequisites.sql', 'utf8'))
})
afterEach(() => db.close())
function raw(provider = 'alpaca') {
  db.prepare("INSERT INTO market_bars VALUES (1,'2026-01-02T05:00:00Z','1Day','raw',?)").run(
    provider
  )
}
test('shared worker/request query rejects adjusted-only data without writes', () => {
  const before = db.prepare('SELECT total_changes() AS n').get()!.n
  const report = stockPrerequisites(db, start, end)
  expect(report.canPrepare).toBe(false)
  expect(report.rawBars).toBe(0)
  expect(report.requestedSessions).toBe(2)
  expect(report.blockers).toContain(
    'Raw daily bars are missing; adjusted scanner bars cannot substitute'
  )
  expect(db.prepare('SELECT total_changes() AS n').get()!.n).toBe(before)
})
test('partial coverage and benchmark absence stay explicit, not qualified', () => {
  raw()
  const report = stockPrerequisites(db, start, end)
  expect(report.canPrepare).toBe(true)
  expect(report.quality.assessmentReady).toBe(false)
  expect(report.quality.assessmentBlockers).toHaveLength(2)
  expect([report.instruments, report.usableInstruments, report.missingSectors]).toEqual([2, 1, 1])
  expect(report.benchmarkBars).toBe(0)
  expect(report.coveredEnd).toBe('2026-01-02T21:00:00Z')
  expect(report.note).toContain('not qualification')
})
test('session-close interval is inclusive/exclusive and ambiguous sources fail closed', () => {
  raw()
  expect(stockPrerequisites(db, start, '2026-01-02T21:00:00Z').canPrepare).toBe(false)
  expect(stockPrerequisites(db, '2026-01-02T21:00:00Z', end).canPrepare).toBe(true)
  raw('other')
  expect(stockPrerequisites(db, start, end).ambiguousSessions).toBe(1)
  expect(stockPrerequisites(db, start, end).canPrepare).toBe(false)
})
