import 'server-only'
import { createHash, randomUUID } from 'node:crypto'
import { researchDatabase } from './research-store'
import { SystemsInputError } from './systems-store'
const parse = (x: unknown) => {
  try {
    return JSON.parse(String(x || '{}'))
  } catch {
    return {}
  }
}
const hash = (x: unknown) => createHash('sha256').update(stable(x)).digest('hex')
function stable(x: any): string {
  return JSON.stringify(
    x && typeof x === 'object'
      ? Array.isArray(x)
        ? x.map((v) => JSON.parse(stable(v)))
        : Object.fromEntries(
            Object.keys(x)
              .sort()
              .map((k) => [k, JSON.parse(stable(x[k]))])
          )
      : x
  )
}
function required(x: unknown, name: string, max = 2000): string {
  if (typeof x !== 'string' || !x.trim() || x.length > max)
    throw new SystemsInputError(`${name} is required (up to ${max} characters)`)
  return x.trim()
}
export function readLab(asset: string, id?: string) {
  return researchDatabase(false, (db) => {
    const previews = db
      .prepare(
        'SELECT p.*,j.status,j.error,j.progress,s.name,s.config_json,s.draft_revision FROM research_previews p JOIN workspace_jobs j ON j.id=p.id JOIN research_snapshots s ON s.id=p.snapshot_id WHERE s.asset=? ORDER BY p.created_at DESC LIMIT 30'
      )
      .all(asset)
      .map(({ result_json, ...r }) => {
        const result = parse(result_json)
        // Metrics calculated in the worker over all observations; only display is sampled.
        for (const name of ['continuous', 'base', 'double_cost'])
          if (result[name]?.equity_curve?.length > 600) {
            const curve = result[name].equity_curve
            result[name].equity_curve = Array.from(
              { length: 600 },
              (_, i) => curve[Math.floor((i * (curve.length - 1)) / 599)]
            )
          }
        if (result.continuous?.fills)
          result.continuous.fills = result.continuous.fills.slice(0, 200)
        return { ...r, id: r.id, config: parse(r.config_json), result }
      })
    return {
      previews: id ? previews.filter((p) => p.id === id) : previews,
      experiments: db
        .prepare(
          'SELECT * FROM research_experiments WHERE asset=? ORDER BY created_at DESC LIMIT 50'
        )
        .all(asset)
        .map((r) => ({
          ...r,
          plan: parse(r.plan_json),
          attempts: db
            .prepare(
              'SELECT a.*,j.status,j.error FROM research_attempts a JOIN workspace_jobs j ON j.id=a.id WHERE experiment_id=? ORDER BY a.created_at DESC LIMIT 100'
            )
            .all(r.id!),
          reviews: db
            .prepare(
              'SELECT * FROM research_reviews WHERE experiment_id=? ORDER BY created_at DESC LIMIT 50'
            )
            .all(r.id!),
        })),
      snapshots: db
        .prepare(
          'SELECT id,name,config_json,created_at FROM research_snapshots WHERE asset=? ORDER BY created_at DESC LIMIT 100'
        )
        .all(asset)
        .map((r) => ({ ...r, config: parse(r.config_json) })),
      datasets: db
        .prepare(
          'SELECT id,manifest_json,created_at FROM system_datasets WHERE asset=? ORDER BY created_at DESC LIMIT 30'
        )
        .all(asset)
        .map((r) => ({ ...r, manifest: parse(r.manifest_json) })),
    }
  })
}
export function labCommand(body: Record<string, any>) {
  const asset = body.asset
  if (!['stocks', 'bitcoin'].includes(asset)) throw new SystemsInputError('Choose an asset')
  return researchDatabase(true, (db) => {
    db.exec('BEGIN IMMEDIATE')
    try {
      const at = new Date().toISOString()
      const queue = (id: string, kind: string, payload: Record<string, any>) => {
        const old = db.prepare('SELECT payload_json FROM workspace_jobs WHERE id=?').get(id)
        if (old) {
          if (stable(parse(old.payload_json)) !== stable(payload))
            throw new SystemsInputError('Request identifier reused')
          return
        }
        if (
          Number(
            db
              .prepare(
                "SELECT count(*) n FROM workspace_jobs WHERE kind!='chart' AND status IN ('queued','running')"
              )
              .get()?.n
          ) >= 10
        )
          throw new SystemsInputError('Research queue is full')
        db.prepare(
          'INSERT INTO workspace_jobs(id,kind,payload_json,created_at) VALUES (?,?,?,?)'
        ).run(id, kind, stable(payload), at)
      }
      const snapshot = (config: any, name: string) => {
        if (
          !config ||
          typeof config !== 'object' ||
          Array.isArray(config) ||
          stable(config).length > 10000 ||
          config.asset !== asset
        )
          throw new SystemsInputError('A bounded configuration for this asset is required')
        const id = hash({ asset, config })
        db.prepare(
          'INSERT OR IGNORE INTO research_snapshots(id,asset,config_json,name,created_at) VALUES (?,?,?,?,?)'
        ).run(id, asset, stable(config), name, at)
        return id
      }
      const enqueuePreview = (id: string, snapshotId: string, params: Record<string, any>) => {
        if (
          !db
            .prepare('SELECT id FROM research_snapshots WHERE id=? AND asset=?')
            .get(snapshotId, asset)
        )
          throw new SystemsInputError('Unknown research snapshot')
        const start = new Date(params.start),
          end = new Date(params.end)
        if (
          !Number.isFinite(+start) ||
          !Number.isFinite(+end) ||
          +start >= +end ||
          +end > Date.now()
        )
          throw new SystemsInputError('Choose an ordered historical interval')
        if (
          !db
            .prepare('SELECT id FROM system_datasets WHERE id=? AND asset=?')
            .get(String(params.dataset), asset)
        )
          throw new SystemsInputError('Choose retained research data for this asset')
        if (![1, 2, 3].includes(Number(params.costMultiplier || 1)))
          throw new SystemsInputError('Unsupported cost scenario')
        queue(id, 'preview', {
          asset,
          snapshot: snapshotId,
          dataset: String(params.dataset),
          start: start.toISOString(),
          end: end.toISOString(),
          costMultiplier: Number(params.costMultiplier || 1),
          startingCash: 1000,
          inspectOnly: Boolean(params.inspectOnly),
        })
        db.prepare(
          'INSERT OR IGNORE INTO research_previews(id,snapshot_id,created_at) VALUES (?,?,?)'
        ).run(id, snapshotId, at)
      }
      let result: Record<string, unknown>
      if (body.action === 'preview') {
        const id = required(body.requestId, 'Request ID', 120)
        const sid = snapshot(
          body.document,
          required(body.name || 'Draft preview', 'Snapshot name', 120)
        )
        enqueuePreview(id, sid, body)
        result = { id, snapshot: sid, status: 'queued', authority: 'research-only' }
      } else if (body.action === 'experiment') {
        const id = required(body.requestId, 'Request ID', 120)
        const baseline = required(body.baseline, 'Baseline snapshot', 64),
          candidate = required(body.candidate, 'Candidate snapshot', 64)
        if (baseline === candidate)
          throw new SystemsInputError('Choose distinct baseline and candidate configurations')
        for (const sid of [baseline, candidate])
          if (
            !db.prepare('SELECT 1 FROM research_snapshots WHERE id=? AND asset=?').get(sid, asset)
          )
            throw new SystemsInputError('Unknown snapshot')
        if (
          !db
            .prepare('SELECT 1 FROM system_datasets WHERE id=? AND asset=?')
            .get(String(body.dataset), asset)
        )
          throw new SystemsInputError('Choose retained data')
        if (!(Date.parse(body.start) < Date.parse(body.end)) || Date.parse(body.end) > Date.now())
          throw new SystemsInputError('Choose a historical interval')
        if (
          body.parent &&
          !db
            .prepare('SELECT 1 FROM research_experiments WHERE id=? AND asset=?')
            .get(String(body.parent), asset)
        )
          throw new SystemsInputError('Unknown parent experiment')
        const plan = {
          hypothesis: required(body.hypothesis, 'Hypothesis'),
          mechanism: required(body.mechanism, 'Mechanism'),
          primaryOutcome: required(body.primaryOutcome, 'Primary outcome'),
          riskConstraint: required(body.riskConstraint, 'Risk constraint'),
          selectionRule: required(body.selectionRule, 'Selection rule'),
          reviewPoint: required(body.reviewPoint, 'Stopping/review point'),
          baseline,
          candidate,
          dataset: String(body.dataset),
          start: new Date(body.start).toISOString(),
          end: new Date(body.end).toISOString(),
          costMultiplier: 1,
          startingCash: 1000,
          authority: 'research-only',
          legacySearchHistory: 'unknown',
        }
        const old = db.prepare('SELECT plan_json FROM research_experiments WHERE id=?').get(id)
        if (old && stable(parse(old.plan_json)) !== stable(plan))
          throw new SystemsInputError('Experiment ID reused')
        db.prepare('INSERT OR IGNORE INTO research_experiments VALUES (?,?,?,?,?)').run(
          id,
          asset,
          body.parent || null,
          stable(plan),
          at
        )
        result = { id, status: 'preregistered' }
      } else if (body.action === 'run_experiment') {
        const row = db
          .prepare('SELECT * FROM research_experiments WHERE id=? AND asset=?')
          .get(required(body.id, 'Experiment'), asset)
        if (!row) throw new SystemsInputError('Unknown experiment')
        const plan = parse(row.plan_json),
          request = required(body.requestId, 'Request ID', 120)
        const ids = []
        for (const role of ['baseline', 'candidate']) {
          const id = request + '-' + role
          enqueuePreview(id, plan[role], plan)
          db.prepare('INSERT OR IGNORE INTO research_attempts VALUES (?,?,?,?,?,?)').run(
            id,
            String(row.id),
            plan[role],
            role,
            null,
            at
          )
          ids.push(id)
        }
        result = { ids, status: 'queued', authority: 'research-only' }
      } else if (body.action === 'review') {
        if (
          !db
            .prepare('SELECT 1 FROM research_experiments WHERE id=? AND asset=?')
            .get(String(body.id), asset)
        )
          throw new SystemsInputError('Unknown experiment')
        if (
          ![
            'invalid inputs',
            'not supported',
            'inconclusive',
            'promising historically',
            'supported by additional forward evidence',
          ].includes(body.conclusion)
        )
          throw new SystemsInputError('Choose a research conclusion')
        const id = required(body.requestId, 'Review ID', 120)
        const explanation = required(body.explanation, 'Evidence and next test')
        const old = db.prepare('SELECT * FROM research_reviews WHERE id=?').get(id)
        if (
          old &&
          (old.experiment_id !== body.id ||
            old.conclusion !== body.conclusion ||
            old.explanation !== explanation)
        )
          throw new SystemsInputError('Review ID reused')
        db.prepare('INSERT OR IGNORE INTO research_reviews VALUES (?,?,?,?,?)').run(
          id,
          body.id,
          body.conclusion,
          explanation,
          at
        )
        result = { id, status: 'reviewed', authority: 'unchanged' }
      } else if (body.action === 'demo') {
        if (asset !== 'bitcoin') throw new SystemsInputError('Demonstration uses Bitcoin only')
        const id = required(body.requestId, 'Request ID', 120)
        queue(id, 'research_demo', { asset, demonstration: true })
        result = { id, status: 'queued' }
      } else if (body.action === 'cancel') {
        const id = required(body.id, 'Job ID', 120)
        db.prepare(
          "UPDATE workspace_jobs SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'canceled' ELSE status END WHERE id=? AND kind IN ('preview','research_demo') AND json_extract(payload_json,'$.asset')=? AND status IN ('queued','running')"
        ).run(id, asset)
        result = { id, status: 'cancellation requested' }
      } else throw new SystemsInputError('Unknown research action')
      db.exec('COMMIT')
      return result
    } catch (e) {
      db.exec('ROLLBACK')
      throw e
    }
  })
}
