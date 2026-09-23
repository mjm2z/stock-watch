jest.mock('server-only', () => ({}))
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { readResearch, writeResearch } from '@/lib/research-store'
let directory: string
const originalPath = process.env.STOCK_WATCH_DATABASE_PATH
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'stock-watch-research-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'research.db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  db.exec(readFileSync('worker/migrations/012_shared_research.sql', 'utf8')); db.close()
})
afterEach(() => {
  if (originalPath === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = originalPath
  rmSync(directory, { recursive: true, force: true })
})
test('shared watchlist survives new connections and import does not overwrite existing notes', () => {
  writeResearch({ action: 'watch', ticker: 'aapl', notes: 'Original' })
  writeResearch({ action: 'watch', ticker: 'AAPL', notes: 'Imported' })
  expect(readResearch().watchlist).toEqual([expect.objectContaining({ ticker: 'AAPL', notes: 'Original' })])
  writeResearch({ action: 'unwatch', ticker: 'AAPL' })
  expect(readResearch().watchlist).toHaveLength(0)
})
test('journal preserves both original and later assessments and filters by ticker', () => {
  const note = { action: 'note', ticker: 'AAPL', hypothesis: 'Test thesis', horizon: 21, review_on: '2026-10-20', assessment: 'open' }
  writeResearch(note); writeResearch({ ...note, assessment: 'invalidated' })
  expect(readResearch('AAPL').notes).toHaveLength(2)
  expect(readResearch('MSFT').notes).toHaveLength(0)
  expect(() => writeResearch({ ...note, review_on: '2026-02-31' })).toThrow('valid review date')
  expect(() => writeResearch({ ...note, horizon: 0 })).toThrow('supported horizon')
  expect(() => writeResearch({ ...note, ticker: "AAPL'; DELETE" })).toThrow('valid ticker')
})
