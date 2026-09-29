jest.mock('server-only', () => ({}))
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { DatabaseSync } from 'node:sqlite'
import { activity, inspection } from '@/lib/inspection-store'
const original = process.env.STOCK_WATCH_DATABASE_PATH
let directory: string
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'inspection-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'app.db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  for (const name of readdirSync('worker/migrations')
    .filter((n) => n.endsWith('.sql'))
    .sort())
    db.exec(readFileSync('worker/migrations/' + name, 'utf8'))
  db.prepare('INSERT INTO system_versions VALUES (?,?,?,?,?,?,?)').run(
    'v',
    'bitcoin',
    'trend',
    '{}',
    'hash',
    '2026-01-01',
    'System'
  )
  db.prepare('INSERT INTO btc_accounts(id,created_at) VALUES (?,?)').run(
    'automated-btc',
    '2026-01-01'
  )
  for (let i = 0; i < 3; i++)
    db.prepare(
      'INSERT INTO btc_orders(id,version_id,account_id,side,quantity,reference_price,created_at,updated_at,reason) VALUES (?,?,?,?,?,?,?,?,?)'
    ).run(
      'order-' + i,
      'v',
      'automated-btc',
      'buy',
      '0.1',
      '100',
      '2026-01-01',
      '2026-01-01',
      'fixture'
    )
  db.close()
})
afterEach(() => {
  if (original === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = original
  rmSync(directory, { recursive: true, force: true })
})
test('market reference prices never become executable limits and reads grant no authority', () => {
  const result = inspection(
    new URLSearchParams({ asset: 'bitcoin', symbol: 'BTC/USD', scope: 'automated' })
  )
  expect(result.levels.filter((l) => l.layer === 'orders')).toHaveLength(3)
  expect(result.levels.every((l) => l.price === undefined)).toBe(true)
  expect(result.levels.every((l) => l.account === 'automated-btc')).toBe(true)
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  expect(db.prepare('SELECT count(*) n FROM workspace_jobs').get()?.n).toBe(0)
  expect(db.prepare('SELECT count(*) n FROM btc_orders').get()?.n).toBe(3)
  db.close()
})
test('prospective activity uses stable cursor pages and asset/scope isolation', () => {
  const query = new URLSearchParams({ asset: 'bitcoin', scope: 'automated', limit: '2' })
  const first = activity(query)
  expect(first.rows).toHaveLength(2)
  expect(first.next).not.toBeNull()
  query.set('before', first.next!)
  const second = activity(query)
  expect(second.rows).toHaveLength(1)
  expect(first.rows.map((r) => r.id)).not.toContain(second.rows[0].id)
  expect(activity(new URLSearchParams({ asset: 'stocks', scope: 'automated' })).rows).toHaveLength(
    0
  )
  expect(() =>
    inspection(new URLSearchParams({ asset: 'stocks', symbol: '../../orders' }))
  ).toThrow('Invalid')
})
