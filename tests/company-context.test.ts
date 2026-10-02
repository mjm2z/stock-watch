jest.mock('server-only', () => ({}))
import { DatabaseSync } from 'node:sqlite'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { companyContext } from '@/lib/company-context'
let folder: string
let db: DatabaseSync
let previous: string | undefined
beforeEach(() => {
  previous = process.env.STOCK_WATCH_DATABASE_PATH
  folder = mkdtempSync(join(tmpdir(), 'company-context-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(folder, 'test.db')
  db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  db.exec(readFileSync('worker/migrations/025_company_context.sql', 'utf8'))
})
afterEach(() => {
  db.close()
  rmSync(folder, { recursive: true, force: true })
  if (previous === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = previous
})
test('coalesces repeated requests and bounds the provider queue', () => {
  expect(companyContext('aapl').status).toBe('queued')
  expect(companyContext('AAPL').status).toBe('queued')
  expect(db.prepare('SELECT count(*) AS n FROM company_context').get()!.n).toBe(1)
  for (let i = 0; i < 30; i++) companyContext(`T${i}`)
  expect(db.prepare('SELECT count(*) AS n FROM company_context').get()!.n).toBe(20)
})
test('preserves stale payload and respects provider-failure cooldown', () => {
  db.prepare(
    'INSERT INTO company_context(symbol,status,requested_at,retry_after,payload_json,error) VALUES (?,?,?,?,?,?)'
  ).run('AAPL', 'unavailable', '2020-01-01', '2999-01-01', '{"name":"Previous"}', 'Unavailable')
  expect(companyContext('AAPL')).toMatchObject({
    status: 'unavailable',
    stale: true,
    data: { name: 'Previous' },
  })
  db.prepare("UPDATE company_context SET retry_after='2020-01-01'").run()
  expect(companyContext('AAPL')).toMatchObject({
    status: 'queued',
    stale: true,
    data: { name: 'Previous' },
  })
})
test('evicts display-only projections at the 500-symbol cap and rejects invalid tickers', () => {
  const insert = db.prepare(
    "INSERT INTO company_context(symbol,status,requested_at,retry_after) VALUES (?,'ready','2020-01-01','2999-01-01')"
  )
  for (let i = 0; i < 500; i++) insert.run(`T${i}`)
  companyContext('AAPL')
  expect(db.prepare('SELECT count(*) AS n FROM company_context').get()!.n).toBe(500)
  expect(() => companyContext('../../bad')).toThrow('valid ticker')
})
