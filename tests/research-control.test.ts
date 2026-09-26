jest.mock('server-only', () => ({}))
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { controlCommand, controlOverview, activity, runDetail } from '@/lib/research-control'
let directory: string
const original = process.env.STOCK_WATCH_DATABASE_PATH
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'research-control-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'test.db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  for (const m of [
    '016_systems',
    '017_bitcoin_automation',
    '018_workspace',
    '019_research_control',
  ])
    db.exec(readFileSync('worker/migrations/' + m + '.sql', 'utf8'))
  db.prepare('INSERT INTO system_versions VALUES (?,?,?,?,?,?,?)').run(
    'version',
    'bitcoin',
    'trend',
    '{}',
    'hash',
    'Test trend',
    '2026-09-26'
  )
  db.close()
})
afterEach(() => {
  if (original === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = original
  rmSync(directory, { recursive: true, force: true })
})
test('policy is versioned and cannot weaken below approved threshold', () => {
  expect(controlOverview('bitcoin').policy?.threshold).toBe(0.8)
  expect(() => controlCommand({ action: 'policy', threshold: 0.79 })).toThrow('80%')
  controlCommand({ action: 'policy', threshold: 0.85, enabled: false })
  expect(controlOverview('bitcoin').policy?.id).toBe(2)
  expect(controlOverview('bitcoin').policy?.enabled).toBe(0)
})
test('operator evaluation has durable idempotency and independent dataset scope', () => {
  const request = { action: 'evaluate', version: 'version', requestId: 'job1' }
  expect(controlCommand(request)).toEqual(controlCommand(request))
  const overview = controlOverview('bitcoin')
  expect(overview.trials).toHaveLength(1)
  expect((overview.trials[0] as Record<string, unknown>).budget).toBe('200')
  expect((overview.trials[0] as Record<string, unknown>).batch_id).toBe('manual-job1')
  expect(() => controlCommand({ ...request, requestId: 'job2' })).toThrow('pending')
})
test('combined activity filters paginate and exclude chart jobs', () => {
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  for (let i = 0; i < 25; i++)
    db.prepare(
      "INSERT INTO workspace_jobs(id,kind,payload_json,created_at,status) VALUES (?,'observe',?,'2026-09-26','succeeded')"
    ).run('j' + i, JSON.stringify({ asset: 'bitcoin', version: 'version' }))
  db.prepare(
    "INSERT INTO workspace_jobs(id,kind,payload_json,created_at) VALUES ('chart','chart',?,'2026-09-26')"
  ).run(JSON.stringify({ asset: 'bitcoin' }))
  db.close()
  const p = new URLSearchParams({
    asset: 'bitcoin',
    version: 'version',
    status: 'succeeded',
    page: '1',
  })
  const result = activity(p)
  expect(result.total).toBe(25)
  expect(result.rows).toHaveLength(5)
  p.set('mode', 'backtesting')
  expect(activity(p).rows).toHaveLength(0)
})
test('evidence rejects unsafe identifiers and unknown proposals cannot become code', () => {
  expect(() => runDetail('../secret', true)).toThrow('identifier')
  expect(() =>
    controlCommand({ action: 'proposal', id: 'proposal', state: 'reviewed', version: 'missing' })
  ).toThrow('published')
})
