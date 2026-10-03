jest.mock('server-only', () => ({}))
import { DatabaseSync } from 'node:sqlite'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { filingDetails } from '@/lib/filing-details'
let folder: string
let db: DatabaseSync
let previous: string | undefined
beforeEach(() => {
  previous = process.env.STOCK_WATCH_DATABASE_PATH
  folder = mkdtempSync(join(tmpdir(), 'company-context-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(folder, 'test.db')
  db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  db.exec(readFileSync('worker/migrations/025_company_context.sql', 'utf8'))
  db.exec(readFileSync('worker/migrations/026_filing_details.sql', 'utf8'))
  db.prepare(
    "INSERT INTO company_context(symbol,status,requested_at,payload_json) VALUES ('AAPL','ready','2026-01-01',?)"
  ).run(
    JSON.stringify({
      filings: Array.from({ length: 10 }, (_, i) => ({ accession: `0000320193-26-00000${i}` })),
    })
  )
})
afterEach(() => {
  db.close()
  rmSync(folder, { recursive: true, force: true })
  if (previous === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = previous
})

test('validates ownership, coalesces requests, bounds queue and preserves cooldown', () => {
  expect(() => filingDetails('AAPL', '0000999999-26-000001')).toThrow('issuer')
  for (let i = 0; i < 10; i++) filingDetails('AAPL', `0000320193-26-00000${i}`)
  expect(db.prepare('SELECT count(*) n FROM filing_details').get()!.n).toBe(5)
  expect(filingDetails('AAPL', '0000320193-26-000000').status).toBe('queued')
  db.exec(
    `UPDATE filing_details SET status='unavailable',retry_after='2999-01-01',payload_json='{"excerpt":"old"}'`
  )
  expect(filingDetails('AAPL', '0000320193-26-000000')).toMatchObject({
    status: 'unavailable',
    stale: true,
    data: { excerpt: 'old' },
  })
})
