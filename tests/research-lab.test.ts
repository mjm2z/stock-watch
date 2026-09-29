jest.mock('server-only', () => ({}))
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { DatabaseSync } from 'node:sqlite'
import { labCommand, readLab } from '@/lib/research-lab'
import { workspaceCommand } from '@/lib/workspace-store'
let directory: string
const original = process.env.STOCK_WATCH_DATABASE_PATH
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'research-lab-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'app.db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  for (const file of readdirSync('worker/migrations')
    .filter((f) => f.endsWith('.sql'))
    .sort())
    db.exec(readFileSync('worker/migrations/' + file, 'utf8'))
  db.prepare('INSERT INTO system_datasets VALUES (?,?,?,?,?,?)').run(
    'dataset',
    'bitcoin',
    'fixture',
    'sha',
    JSON.stringify({ timeframe: '1Day' }),
    '2026-01-01T00:00:00Z'
  )
  db.close()
})
afterEach(() => {
  if (original === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = original
  rmSync(directory, { recursive: true, force: true })
})
const body = {
  action: 'preview',
  asset: 'bitcoin',
  requestId: 'preview-1',
  name: 'My draft',
  document: { asset: 'bitcoin', protocol: 'visual-rules-v1' },
  dataset: 'dataset',
  start: '2024-01-01',
  end: '2025-01-01',
}
test('immutable research snapshot queues independently without executable records; request retries deduplicate', () => {
  labCommand(body)
  labCommand(body)
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  expect(db.prepare('SELECT count(*) n FROM research_snapshots').get()?.n).toBe(1)
  expect(db.prepare('SELECT count(*) n FROM research_previews').get()?.n).toBe(1)
  for (const table of [
    'system_versions',
    'system_deployments',
    'btc_orders',
    'btc_allocations',
    'btc_enrollments',
    'paper_authorizations',
  ])
    expect(db.prepare('SELECT count(*) n FROM ' + table).get()?.n).toBe(0)
  expect(() => labCommand({ ...body, end: '2025-02-01' })).toThrow('reused')
  labCommand({ action: 'cancel', asset: 'bitcoin', id: 'preview-1' })
  expect(readLab('bitcoin').previews[0]).toMatchObject({ id: 'preview-1', status: 'canceled' })
  db.close()
})
test('optimistic draft revisions reject stale browser saves', () => {
  const draft = workspaceCommand({
    action: 'save_draft',
    asset: 'stocks',
    name: 'Draft',
    document: { asset: 'stocks' },
  })
  workspaceCommand({
    action: 'save_draft',
    asset: 'stocks',
    id: draft.id,
    revision: 1,
    name: 'Updated',
    document: { asset: 'stocks' },
  })
  expect(() =>
    workspaceCommand({
      action: 'save_draft',
      asset: 'stocks',
      id: draft.id,
      revision: 1,
      name: 'Overwrite',
      document: { asset: 'stocks' },
    })
  ).toThrow('changed elsewhere')
  expect(() =>
    workspaceCommand({
      action: 'publish',
      asset: 'stocks',
      draft: draft.id,
      revision: 1,
      requestId: 'stale',
    })
  ).toThrow('changed before publication')
})

test('experiment plan is immutable, attempts keep roles, and a review grants no authority', () => {
  const first = labCommand(body)
  const second = labCommand({
    ...body,
    requestId: 'preview-2',
    document: { ...body.document, allocation: 0.2 },
  })
  const plan = {
    action: 'experiment',
    asset: 'bitcoin',
    requestId: 'experiment-1',
    baseline: first.snapshot,
    candidate: second.snapshot,
    dataset: 'dataset',
    start: '2024-01-01',
    end: '2025-01-01',
    hypothesis: 'Exit sensitivity',
    mechanism: 'Change one component',
    primaryOutcome: 'Net return',
    riskConstraint: 'No worse drawdown',
    selectionRule: 'No selection under 30 trades',
    reviewPoint: 'One paired replay',
  }
  labCommand(plan)
  expect(() => labCommand({ ...plan, hypothesis: 'Rewritten after results' })).toThrow('reused')
  labCommand({ action: 'run_experiment', asset: 'bitcoin', id: 'experiment-1', requestId: 'pair' })
  labCommand({
    action: 'review',
    asset: 'bitcoin',
    id: 'experiment-1',
    requestId: 'review',
    conclusion: 'inconclusive',
    explanation: 'Fixture; no independent investment evidence',
  })
  const experiment = readLab('bitcoin').experiments[0]
  expect(experiment.attempts.map((a) => a.role).sort()).toEqual(['baseline', 'candidate'])
  expect(experiment.reviews[0].conclusion).toBe('inconclusive')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  expect(db.prepare('SELECT count(*) n FROM paper_authorizations').get()?.n).toBe(0)
  expect(db.prepare('SELECT count(*) n FROM system_versions').get()?.n).toBe(0)
  db.close()
})
