jest.mock('server-only', () => ({}))
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { workspaceCommand, readWorkspace, chartRequest } from '@/lib/workspace-store'
let directory: string
const original = process.env.STOCK_WATCH_DATABASE_PATH
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'workspace-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'test.db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  for (const m of ['016_systems', '017_bitcoin_automation', '018_workspace'])
    db.exec(readFileSync(`worker/migrations/${m}.sql`, 'utf8'))
  db.close()
})
afterEach(() => {
  jest.useRealTimers()
  if (original === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = original
  rmSync(directory, { recursive: true, force: true })
})
test('recent history remains visible during rollover, without substituting custom windows', () => {
  jest.useFakeTimers().setSystemTime(new Date('2026-09-26T20:01:00Z'))
  chartRequest('1Y')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  const job = db.prepare('SELECT id,payload_json FROM workspace_jobs').get()!
  const payload = JSON.parse(String(job.payload_json))
  const bars = [{ at: '2026-09-25T00:00:00Z', close: 100 }]
  db.prepare('INSERT INTO crypto_chart_cache VALUES (?,?,?)').run(
    payload.key,
    JSON.stringify({ bars, resolution: '1Day' }),
    new Date().toISOString()
  )
  // A daily chart shares the hour's work, instead of discarding it every five minutes.
  jest.setSystemTime(new Date('2026-09-26T20:51:00Z'))
  expect(chartRequest('1Y').bars).toEqual(bars)
  expect(db.prepare('SELECT count(*) AS n FROM workspace_jobs').get()!.n).toBe(1)
  jest.setSystemTime(new Date('2026-09-26T21:01:00Z'))
  const next = chartRequest('1Y')
  expect(next.bars).toEqual(bars)
  expect(next.stale).toBe(true)
  expect(next.refreshing).toBe(true)
  expect(db.prepare('SELECT count(*) AS n FROM workspace_jobs').get()!.n).toBe(2)
  expect(chartRequest('custom', '2025-09-26T00:00:00Z', '2026-09-26T00:00:00Z').bars).toEqual([])
  db.close()
})
test('drafts remain editable while queued publication is frozen and idempotent', () => {
  const d = workspaceCommand({
    action: 'save_draft',
    asset: 'stocks',
    name: 'My system',
    document: { entry_rules: {} },
  })
  const body = { action: 'publish', asset: 'stocks', draft: d.id, requestId: 'publish-1' }
  workspaceCommand(body)
  workspaceCommand(body)
  expect(readWorkspace('stocks').jobs).toHaveLength(1)
  workspaceCommand({
    action: 'save_draft',
    asset: 'stocks',
    id: d.id,
    name: 'Revised',
    document: { entry_rules: { changed: true } },
  })
  const payload = JSON.parse(
    String((readWorkspace('stocks').jobs[0] as Record<string, unknown>).payload_json)
  )
  expect(payload.snapshot.name).toBe('My system')
  expect((readWorkspace('stocks').drafts[0] as Record<string, unknown>).name).toBe('Revised')
  expect(() =>
    workspaceCommand({
      action: 'save_draft',
      asset: 'bitcoin',
      id: d.id,
      name: 'Changed asset',
      document: {},
    })
  ).toThrow('asset')
  workspaceCommand({ action: 'cancel', asset: 'stocks', id: 'publish-1' })
  expect((readWorkspace('stocks').jobs[0] as Record<string, unknown>).status).toBe('queued')
})
test('chart requests are bounded and share collection work without inventing prices', () => {
  const a = chartRequest('1M'),
    b = chartRequest('1M')
  expect(a.bars).toEqual([])
  expect(b.status).toBe('queued')
  expect(readWorkspace('bitcoin').jobs).toHaveLength(1)
  expect(() => chartRequest('custom', '2000-01-01', '2026-01-01')).toThrow('ten years')
  expect(() => chartRequest('garbage')).toThrow('Unknown')
})

test('archiving versions retains history and cannot hide paper authority', () => {
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  db.prepare('INSERT INTO system_versions VALUES (?,?,?,?,?,?,?)').run(
    'v',
    'stocks',
    'visual',
    '{}',
    'hash',
    'now',
    'Original name'
  )
  db.close()
  workspaceCommand({ action: 'archive_version', asset: 'stocks', id: 'v' })
  expect((readWorkspace('stocks').versions[0] as Record<string, unknown>).archived).toBe(1)
  workspaceCommand({ action: 'archive_version', asset: 'stocks', id: 'v', archived: false })
  const active = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  active
    .prepare('INSERT INTO system_deployments(id,version_id,mode,started_at) VALUES (?,?,?,?)')
    .run('dep', 'v', 'paper', 'original-date')
  active.close()
  expect(() => workspaceCommand({ action: 'archive_version', asset: 'stocks', id: 'v' })).toThrow(
    'remain visible'
  )
  expect((readWorkspace('stocks').versions[0] as Record<string, unknown>).hypothesis).toBe(
    'Original name'
  )
})
