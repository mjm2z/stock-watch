jest.mock('server-only', () => ({}))
import { DatabaseSync } from 'node:sqlite'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { randomUUID } from 'node:crypto'
import { writeLean, readLean } from '@/lib/lean-store'
let db: DatabaseSync, folder: string, previous: string | undefined
beforeEach(() => {
  previous = process.env.STOCK_WATCH_DATABASE_PATH
  folder = mkdtempSync(join(tmpdir(), 'lean-store-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(folder, 'test.db')
  db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  db.exec(readFileSync('worker/migrations/016_systems.sql', 'utf8'))
  db.exec(readFileSync('worker/migrations/027_lean_comparisons.sql', 'utf8'))
  db.prepare('INSERT INTO system_versions VALUES (?,?,?,?,?,?,?)').run(
    'version',
    'bitcoin',
    'trend',
    JSON.stringify({ asset: 'bitcoin', template: 'trend' }),
    'hash',
    '2026-01-01',
    ''
  )
  db.prepare('INSERT INTO system_datasets VALUES (?,?,?,?,?,?)').run(
    'dataset',
    'bitcoin',
    'unused',
    'hash',
    JSON.stringify({ timeframe: '1Hour' }),
    '2026-01-01'
  )
  db.prepare('INSERT INTO lean_runner_health VALUES (1,?,?)').run(
    new Date().toISOString(),
    JSON.stringify({ configured: true, healthy: true })
  )
})
afterEach(() => {
  db.close()
  rmSync(folder, { recursive: true, force: true })
  if (previous === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = previous
})
test('coalesces duplicate identities and limits pending comparisons', () => {
  const id = randomUUID()
  const request = { action: 'create', id, version: 'version', dataset: 'dataset' }
  writeLean(request)
  writeLean(request)
  expect(readLean().runs).toHaveLength(1)
  for (let i = 0; i < 4; i++) writeLean({ ...request, id: randomUUID() })
  expect(() => writeLean({ ...request, id: randomUUID() })).toThrow('queue is full')
  expect(() => writeLean({ ...request, dataset: 'other' })).toThrow('different comparison')
})
test('unconfigured and stale runners cannot accept work', () => {
  db.exec("UPDATE lean_runner_health SET updated_at='2000-01-01'")
  expect(() =>
    writeLean({ action: 'create', id: randomUUID(), version: 'version', dataset: 'dataset' })
  ).toThrow('unavailable')
  expect(readLean().health.stale).toBe(true)
})
test('cancel records intent without modifying system activation', () => {
  const id = randomUUID()
  writeLean({ action: 'create', id, version: 'version', dataset: 'dataset' })
  writeLean({ action: 'cancel', id })
  expect(readLean().runs[0].cancel_requested).toBe(1)
  expect(db.prepare('SELECT count(*) n FROM system_deployments').get()!.n).toBe(0)
})
