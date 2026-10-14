import 'server-only'
import { DatabaseSync } from 'node:sqlite'
import { researchDatabase } from './research-store'

export class ExperimentInputError extends Error {}
export type ExperimentAsset = 'stocks' | 'bitcoin'
export function experimentAsset(value: unknown): ExperimentAsset {
  if (value !== 'stocks' && value !== 'bitcoin')
    throw new ExperimentInputError('Choose stocks or bitcoin.')
  return value
}
function identifier(value: unknown, name: string) {
  if (typeof value !== 'string' || !/^[a-zA-Z0-9_-]{8,100}$/.test(value))
    throw new ExperimentInputError(`Invalid ${name}.`)
  return value
}
export function readExperiments(asset: ExperimentAsset) {
  return researchDatabase(false, (db) => ({
    asset,
    batches: db
      .prepare('SELECT * FROM experiment_batches WHERE asset=? ORDER BY created DESC LIMIT 20')
      .all(asset)
      .map((row) => ({ ...row, plan: JSON.parse(String(row.plan_json)), plan_json: undefined })),
    instances: db
      .prepare(
        `SELECT i.*,v.family,b.asset,b.expires,b.risk_reason FROM experiment_instances i
      JOIN experiment_batches b ON b.id=i.batch_id JOIN experiment_versions v ON v.id=i.version_id
      WHERE b.asset=? ORDER BY b.created DESC,v.family LIMIT 100`
      )
      .all(asset),
    context: db.prepare('SELECT * FROM experiment_context ORDER BY published DESC LIMIT 30').all(),
    health: db.prepare('SELECT * FROM experiment_health ORDER BY component').all(),
    commands: db
      .prepare('SELECT * FROM experiment_commands WHERE asset=? ORDER BY created DESC LIMIT 20')
      .all(asset),
    proposals: db
      .prepare(
        'SELECT * FROM experiment_research_proposals WHERE asset=? ORDER BY created DESC LIMIT 40'
      )
      .all(asset),
    research: db
      .prepare(
        "SELECT id,status,result_json,error,created_at FROM workspace_jobs WHERE kind='experiment_replay' AND json_extract(payload_json,'$.asset')=? ORDER BY created_at DESC LIMIT 20"
      )
      .all(asset),
    owner: db.prepare('SELECT * FROM execution_authority WHERE asset=?').get(asset),
  }))
}
export function experimentDetail(asset: ExperimentAsset, instance: string, before?: string) {
  identifier(instance, 'instance')
  const [time, cursor] = before?.split('|') || []
  if (before && (before.length > 150 || !time || !cursor || !Number.isFinite(Date.parse(time))))
    throw new ExperimentInputError('Invalid decision cursor.')
  return researchDatabase(false, (db) => {
    const row = db
      .prepare(
        `SELECT i.*,v.config_json,b.asset FROM experiment_instances i JOIN experiment_versions v ON v.id=i.version_id
      JOIN experiment_batches b ON b.id=i.batch_id WHERE i.id=? AND b.asset=?`
      )
      .get(instance, asset)
    if (!row) throw new ExperimentInputError('Experiment not found.')
    const decisions = db
      .prepare(
        'SELECT * FROM experiment_decisions WHERE instance_id=? AND (? IS NULL OR cutoff<? OR (cutoff=? AND id>?)) ORDER BY cutoff DESC,id LIMIT 100'
      )
      .all(instance, time || null, time || null, time || null, cursor || '')
    return {
      instance: { ...row, config: JSON.parse(String(row.config_json)), config_json: undefined },
      gaps: db
        .prepare(
          'SELECT * FROM experiment_decision_gaps WHERE instance_id=? ORDER BY start DESC LIMIT 20'
        )
        .all(instance),
      positions: db.prepare('SELECT * FROM experiment_positions WHERE instance_id=?').all(instance),
      orders: db
        .prepare(
          'SELECT * FROM experiment_orders WHERE instance_id=? ORDER BY created DESC LIMIT 100'
        )
        .all(instance),
      decisions: decisions.map((d) => ({
        ...d,
        evidence: JSON.parse(String(d.evidence_json)),
        evidence_json: undefined,
      })),
      next:
        decisions.length === 100
          ? String(decisions[99].cutoff) + '|' + String(decisions[99].id)
          : null,
    }
  })
}
export function decisionEvidence(asset: ExperimentAsset, id: string) {
  identifier(id, 'decision')
  const row = researchDatabase(false, (db) =>
    db
      .prepare(
        `SELECT d.* FROM experiment_decisions d JOIN experiment_instances i ON i.id=d.instance_id
    JOIN experiment_batches b ON b.id=i.batch_id WHERE d.id=? AND b.asset=?`
      )
      .get(id, asset)
  )
  if (!row) throw new ExperimentInputError('Decision not found.')
  const saved = JSON.parse(String(row.evidence_json)) as {
    bars: number[]
    news?: { id: string; revision: string }[]
  }
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH + '.experiment-evidence.db', {
    readOnly: true,
  })
  try {
    const ids = saved.bars.slice(0, 251)
    return {
      ...row,
      evidence: saved,
      articles: (saved.news || [])
        .slice(0, 100)
        .map((n) =>
          db.prepare('SELECT * FROM news WHERE id=? AND revision=? LIMIT 1').get(n.id, n.revision)
        )
        .filter(Boolean),
      bars: ids.length
        ? db
            .prepare(`SELECT * FROM bars WHERE id IN (${ids.map(() => '?').join(',')}) ORDER BY at`)
            .all(...ids)
            .map((b) => ({ ...b, bar: JSON.parse(String(b.payload)), payload: undefined }))
        : [],
    }
  } finally {
    db.close()
  }
}
export function experimentCommand(body: Record<string, unknown>) {
  const asset = experimentAsset(body.asset),
    requestId = identifier(body.requestId, 'request ID'),
    action = String(body.action)
  if (
    !['preview', 'approve', 'pause', 'resume', 'exit', 'exit_and_pause', 'replay'].includes(action)
  )
    throw new ExperimentInputError('Unknown command.')
  const payload: Record<string, string> = { asset }
  if (action === 'approve' || action === 'replay' || body.batch_id)
    payload.batch_id = identifier(body.batch_id, 'batch')
  if (action === 'approve') payload.revision = identifier(body.revision, 'revision')
  if (body.proposal_id) payload.proposal_id = identifier(body.proposal_id, 'proposal')
  if (body.instance_id) payload.instance_id = identifier(body.instance_id, 'instance')
  if (
    !['preview', 'approve', 'replay'].includes(action) &&
    !payload.instance_id &&
    !payload.batch_id
  )
    throw new ExperimentInputError('Choose an instance or batch.')
  if (action === 'replay') {
    for (const key of ['start', 'end']) {
      if (typeof body[key] !== 'string' || !Number.isFinite(Date.parse(body[key])))
        throw new ExperimentInputError('Choose a replay period.')
      payload[key] = new Date(body[key]).toISOString()
    }
    const days = (Date.parse(payload.end) - Date.parse(payload.start)) / 86400000
    if (!(days > 0 && days <= 14))
      throw new ExperimentInputError('Replay is limited to 14 days per job.')
  }
  return researchDatabase(true, (db) => {
    db.exec('BEGIN IMMEDIATE')
    try {
      if (
        payload.batch_id &&
        !db
          .prepare('SELECT 1 FROM experiment_batches WHERE id=? AND asset=?')
          .get(payload.batch_id, asset)
      )
        throw new ExperimentInputError('Batch does not belong to this asset.')
      if (
        payload.instance_id &&
        !db
          .prepare(
            'SELECT 1 FROM experiment_instances i JOIN experiment_batches b ON b.id=i.batch_id WHERE i.id=? AND b.asset=?'
          )
          .get(payload.instance_id, asset)
      )
        throw new ExperimentInputError('Instance does not belong to this asset.')
      const serialized = JSON.stringify(payload)
      const existing =
        action === 'replay'
          ? db
              .prepare('SELECT kind AS action,payload_json FROM workspace_jobs WHERE id=?')
              .get(requestId)
          : db
              .prepare('SELECT action,payload_json FROM experiment_commands WHERE id=?')
              .get(requestId)
      if (
        existing &&
        (existing.action !== (action === 'replay' ? 'experiment_replay' : action) ||
          existing.payload_json !== serialized)
      )
        throw new ExperimentInputError('Request ID already belongs to another command.')
      if (!existing) {
        if (action === 'replay')
          db.prepare(
            "INSERT INTO workspace_jobs(id,kind,payload_json,created_at) VALUES (?,'experiment_replay',?,?)"
          ).run(requestId, serialized, new Date().toISOString())
        else
          db.prepare(
            'INSERT INTO experiment_commands(id,asset,action,payload_json,created) VALUES (?,?,?,?,?)'
          ).run(requestId, asset, action, serialized, new Date().toISOString())
      }
      db.exec('COMMIT')
      return { id: requestId, status: 'queued' }
    } catch (error) {
      db.exec('ROLLBACK')
      throw error
    }
  })
}
