jest.mock('server-only', () => ({}))
jest.mock('next/server', () => ({
  NextResponse: {
    json: (body: unknown, init?: { status: number }) => ({ body, status: init?.status || 200 }),
  },
}))
import { DatabaseSync } from 'node:sqlite'
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { GET } from '@/app/api/systems/preflight/route'
import { workspaceCommand } from '@/lib/workspace-store'
import type { NextRequest } from 'next/server'
let directory: string
const previous = process.env.STOCK_WATCH_DATABASE_PATH
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'stock-preflight-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  for (const name of readdirSync('worker/migrations')
    .filter((n) => n.endsWith('.sql'))
    .sort())
    db.exec(readFileSync(join('worker/migrations', name), 'utf8'))
  db.exec(
    "INSERT INTO system_versions VALUES ('stock-v1','stocks','visual','{}','immutable','2026-01-01','Test')"
  )
  db.close()
})
afterEach(() => {
  if (previous === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = previous
  rmSync(directory, { recursive: true, force: true })
})
const request = (query: string) =>
  ({
    nextUrl: new URL('http://localhost/api/systems/preflight?' + query),
  }) as unknown as NextRequest
// Worker startup can be disk-bound on shared Linux hosts. This is separate from
// the cached response latency contract asserted below.
async function completedPreflight() {
  const deadline = performance.now() + 30_000
  let response: any
  do {
    await new Promise((resolve) => setTimeout(resolve, 50))
    response = GET(request('asset=stocks&start=2026-01-01&end=2026-01-06'))
    if (response.status !== 202) return response
  } while (performance.now() < deadline)
  throw new Error('Preflight worker did not complete within 30 seconds')
}
jest.setTimeout(35_000)
test('GET distinguishes checking, blocked prerequisites, invalid interval and unavailable database', async () => {
  expect(GET(request('asset=stocks&start=2026-01-01&end=2026-01-06'))).toMatchObject({
    status: 202,
    body: { canPrepare: false, state: 'checking' },
  })
  const response = await completedPreflight()
  expect(response).toMatchObject({ status: 200, body: { state: 'ready', canPrepare: false } })
  const cachedStart = performance.now()
  for (let i = 0; i < 10; i++)
    expect((GET(request('asset=stocks&start=2026-01-01&end=2026-01-06')) as any).status).toBe(200)
  expect(performance.now() - cachedStart).toBeLessThan(500)
  expect(GET(request('asset=bitcoin&start=2026-01-01&end=2026-01-06'))).toMatchObject({
    status: 400,
  })
  expect(GET(request('asset=stocks&start=2026-01-06&end=2026-01-01'))).toMatchObject({
    status: 400,
  })
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'missing')
  expect(GET(request('asset=stocks&start=2026-01-01&end=2026-01-06'))).toMatchObject({
    status: 503,
  })
})
test('new stock backtest is rejected before any queue write; prior request retry stays idempotent', async () => {
  const body = {
    action: 'backtest',
    asset: 'stocks',
    requestId: 'request-1',
    version: 'stock-v1',
    start: '2026-01-01',
    end: '2026-01-06',
  }
  expect(() => workspaceCommand(body)).toThrow('Checking captured data')
  await completedPreflight()
  expect(() => workspaceCommand(body)).toThrow('Raw daily bars are missing')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  expect(db.prepare('SELECT COUNT(*) AS n FROM workspace_jobs').get()!.n).toBe(0)
  db.prepare('INSERT INTO workspace_jobs(id,kind,payload_json,created_at) VALUES (?,?,?,?)').run(
    'request-1',
    'backtest',
    JSON.stringify(body),
    '2026-01-01'
  )
  expect(() => workspaceCommand(body)).not.toThrow()
  expect(db.prepare('SELECT COUNT(*) AS n FROM workspace_jobs').get()!.n).toBe(1)
  db.close()
})
