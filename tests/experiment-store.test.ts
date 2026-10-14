jest.mock('server-only', () => ({}))
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { experimentCommand, experimentAsset } from '@/lib/experiment-store'
let directory: string
const previous = process.env.STOCK_WATCH_DATABASE_PATH
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'experiment-api-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'test.db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  for (const migration of readdirSync('worker/migrations')
    .filter((n) => n.endsWith('.sql'))
    .sort())
    db.exec(readFileSync(`worker/migrations/${migration}`, 'utf8'))
  db.close()
})
afterEach(() => {
  if (previous === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = previous
  rmSync(directory, { recursive: true, force: true })
})
test('commands are idempotent, bounded and independent of research jobs', () => {
  const body = { asset: 'stocks', action: 'preview', requestId: 'preview-test-123' }
  expect(experimentCommand(body).status).toBe('queued')
  experimentCommand(body)
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  expect(db.prepare('SELECT count(*) n FROM experiment_commands').get()!.n).toBe(1)
  expect(db.prepare('SELECT count(*) n FROM workspace_jobs').get()!.n).toBe(0)
  db.close()
  expect(() => experimentCommand({ ...body, asset: 'bitcoin' })).toThrow('another command')
  expect(() => experimentCommand({ ...body, action: 'trade-live' })).toThrow('Unknown')
})
test('cross-asset and malformed execution authority is rejected', () => {
  expect(() => experimentAsset('crypto')).toThrow('Choose')
  expect(() =>
    experimentCommand({
      asset: 'stocks',
      action: 'approve',
      requestId: 'request-123',
      batch_id: 'missing-batch',
      revision: 'revision-123',
    })
  ).toThrow('does not belong')
  expect(() =>
    experimentCommand({ asset: 'stocks', action: 'pause', requestId: 'request-123' })
  ).toThrow('Choose')
})
