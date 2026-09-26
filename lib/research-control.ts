import 'server-only'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createHash } from 'node:crypto'
import { researchDatabase } from './research-store'
import { SystemsInputError } from './systems-store'
import { assetOf } from './workspace-store'

type Row = Record<string, unknown>
export const parsed = (v: unknown): Record<string, any> => {
  try {
    return JSON.parse(String(v || '{}'))
  } catch {
    return {}
  }
}
const summarize = (raw: unknown) => {
  const result = parsed(raw),
    base = result.base || result.summary || {}
  return {
    netReturn: base.net_return ?? null,
    drawdown: base.maximum_drawdown ?? null,
    winRate: base.win_rate ?? null,
    trades: base.closed_trades ?? null,
    fees: base.fees ?? null,
    startingCash: base.starting_cash ?? null,
    endingEquity: base.ending_equity ?? null,
    metrics: base.metrics || null,
    benchmarks: result.benchmarks || {},
    coverage: result.coverage || {},
    evidence: base.evidence || 'Unavailable',
    warnings: base.warnings || [],
    holdout: result.holdout_status,
    trialCount: result.trial_count ?? null,
  }
}
export function activity(params: URLSearchParams) {
  const asset = assetOf(params.get('asset') || 'stocks'),
    mode = params.get('mode') || 'systems'
  const page = Math.max(0, Math.min(10000, Math.floor(Number(params.get('page')) || 0))),
    size = 20
  const status = params.get('status') || '',
    version = params.get('version') || ''
  return researchDatabase(false, (db) => {
    const where = [
      "json_extract(j.payload_json,'$.asset')=?",
      mode === 'backtesting' ? "j.kind='backtest'" : "j.kind!='chart'",
    ]
    const args: (string | number)[] = [asset]
    if (status) {
      where.push('COALESCE(c.status,r.status,j.status)=?')
      args.push(status)
    }
    if (version) {
      where.push(
        "COALESCE(r.version_id,json_extract(j.payload_json,'$.version'),json_extract(j.result_json,'$.version'))=?"
      )
      args.push(version)
    }
    const joins = `FROM workspace_jobs j LEFT JOIN system_runs r ON r.id=j.id LEFT JOIN system_commands c ON c.id=j.id
      LEFT JOIN system_versions v ON v.id=COALESCE(r.version_id,json_extract(j.payload_json,'$.version'),json_extract(j.result_json,'$.version'))`
    const count = Number(
      db.prepare(`SELECT COUNT(*) AS n ${joins} WHERE ${where.join(' AND ')}`).get(...args)?.n || 0
    )
    const rows = db
      .prepare(
        `SELECT j.*,r.version_id,r.status AS run_status,r.progress AS run_progress,r.error AS run_error,r.result_json AS run_result,
      r.started_at AS run_started,r.finished_at AS run_finished,c.status AS command_status,c.error AS command_error,
      v.hypothesis,v.config_json,s.stage,s.heartbeat_at FROM workspace_jobs j
      LEFT JOIN system_runs r ON r.id=j.id LEFT JOIN system_commands c ON c.id=j.id
      LEFT JOIN system_versions v ON v.id=COALESCE(r.version_id,json_extract(j.payload_json,'$.version'),json_extract(j.result_json,'$.version'))
      LEFT JOIN research_job_stages s ON s.job_id=j.id WHERE ${where.join(' AND ')}
      ORDER BY j.created_at DESC,j.id DESC LIMIT ? OFFSET ?`
      )
      .all(...args, size, page * size)
    return {
      page,
      total: count,
      pages: Math.ceil(count / size),
      rows: rows.map((r) => {
        const body = parsed(r.payload_json),
          config = parsed(r.config_json)
        return {
          id: r.id,
          kind: r.kind,
          status: r.command_status || r.run_status || r.status,
          name: r.hypothesis || body.snapshot?.name || body.name || 'System request',
          version: r.version_id || body.version || parsed(r.result_json).version,
          start: body.start,
          end: body.end,
          timeframe: config.timeframe,
          costMultiplier: body.costMultiplier || 1,
          createdAt: r.created_at,
          startedAt: r.run_started || r.started_at,
          finishedAt: r.run_finished || r.finished_at,
          stage:
            (['succeeded', 'failed', 'canceled'].includes(String(r.run_status || r.status))
              ? r.run_status || r.status
              : r.stage) ||
            (r.run_status === 'queued'
              ? 'Waiting for replay'
              : r.run_status === 'running'
                ? 'Replaying historical events'
                : r.status === 'running'
                  ? 'Preparing data'
                  : r.status),
          heartbeatAt: r.heartbeat_at,
          progress: r.run_progress ?? r.progress,
          error: r.command_error || r.run_error || r.error,
          summary: r.run_result ? summarize(r.run_result) : null,
        }
      }),
    }
  })
}
export function runDetail(id: string, full = false) {
  if (!/^[A-Za-z0-9_-]{1,120}$/.test(id)) throw new SystemsInputError('Invalid run identifier')
  return researchDatabase(false, (db) => {
    const row = db
      .prepare(
        `SELECT r.*,v.hypothesis,v.asset,v.config_json,d.path,d.manifest_json,l.parent_version,l.parent_run,l.changes_json
      FROM system_runs r JOIN system_versions v ON v.id=r.version_id JOIN system_datasets d ON d.id=r.dataset_id
      LEFT JOIN research_lineage l ON l.version_id=r.version_id WHERE r.id=?`
      )
      .get(id)
    if (!row) throw new SystemsInputError('Run not found')
    let result = parsed(row.result_json)
    if (full) {
      const file = join(dirname(String(row.path)), id + '.result.json')
      if (result.result_artifact_sha256 && !existsSync(file))
        throw new SystemsInputError('Full evidence artifact is missing')
      if (existsSync(file)) {
        const raw = readFileSync(file)
        if (
          !result.result_artifact_sha256 ||
          createHash('sha256').update(raw).digest('hex') !== result.result_artifact_sha256
        )
          throw new SystemsInputError('Evidence checksum mismatch')
        result = JSON.parse(raw.toString('utf8'))
      }
    }
    const metric = db.prepare('SELECT payload_json FROM research_metrics WHERE run_id=?').get(id)
    return {
      id: row.id,
      version: row.version_id,
      name: row.hypothesis,
      asset: row.asset,
      status: row.status,
      error: row.error,
      createdAt: row.created_at,
      startedAt: row.started_at,
      finishedAt: row.finished_at,
      config: parsed(row.config_json),
      manifest: parsed(row.manifest_json),
      parentVersion: row.parent_version,
      parentRun: row.parent_run,
      changes: parsed(row.changes_json),
      summary: summarize(row.result_json),
      metrics: metric ? parsed(metric.payload_json) : result.base?.metrics,
      result,
    }
  })
}
export function controlOverview(asset: string) {
  return researchDatabase(false, (db) => ({
    policy: db.prepare('SELECT * FROM research_policies ORDER BY id DESC LIMIT 1').get(),
    batches: db.prepare('SELECT * FROM discovery_batches ORDER BY created_at DESC LIMIT 7').all(),
    trials: db
      .prepare(
        'SELECT t.*,v.hypothesis,(SELECT count(*) FROM discovery_scenarios s WHERE s.trial_id=t.id) AS completed FROM discovery_trials t JOIN system_versions v ON v.id=t.version_id WHERE t.asset=? ORDER BY t.created_at DESC LIMIT 60'
      )
      .all(asset)
      .map(({ result_json, ...r }) => ({ ...r, result: parsed(result_json) })),
    events: db
      .prepare("SELECT * FROM research_events WHERE asset IN (?, 'all') ORDER BY id DESC LIMIT 40")
      .all(asset)
      .map(({ payload_json, ...r }) => ({ ...r, payload: parsed(payload_json) })),
    proposals: db
      .prepare('SELECT * FROM research_proposals ORDER BY retrieved_at DESC LIMIT 30')
      .all(),
    authorizations: db.prepare('SELECT * FROM paper_authorizations').all(),
    health: db
      .prepare(
        "SELECT * FROM btc_health WHERE key IN ('discovery','automatic-paper','data','account','orders','quote')"
      )
      .all(),
    allocations: db
      .prepare('SELECT version_id,budget,cash,quantity,risk_paused,started_at FROM btc_allocations')
      .all(),
  }))
}
export function controlCommand(body: Row) {
  return researchDatabase(true, (db) => {
    const at = new Date().toISOString()
    if (body.action === 'policy') {
      const old = db.prepare('SELECT * FROM research_policies ORDER BY id DESC LIMIT 1').get()!
      const threshold =
        body.threshold === undefined ? Number(old.threshold) : Number(body.threshold)
      if (!Number.isFinite(threshold) || threshold < 0.8 || threshold > 1)
        throw new SystemsInputError('Choose a scenario threshold from 80% to 100%.')
      if (
        (body.enabled !== undefined && typeof body.enabled !== 'boolean') ||
        (body.discoveryEnabled !== undefined && typeof body.discoveryEnabled !== 'boolean')
      )
        throw new SystemsInputError('Boolean policy settings required')
      db.prepare(
        'INSERT INTO research_policies(created_at,enabled,discovery_enabled,threshold,pool,sleeve,entry_cap,reason) VALUES (?,?,?,?,?,?,?,?)'
      ).run(
        at,
        body.enabled === undefined ? Number(old.enabled) : Number(body.enabled),
        body.discoveryEnabled === undefined
          ? Number(old.discovery_enabled)
          : Number(body.discoveryEnabled),
        threshold,
        String(old.pool),
        String(old.sleeve),
        String(old.entry_cap),
        'Operator policy update; previous authorizations require evaluation under this policy'
      )
      return { status: 'saved' }
    }
    if (body.action === 'proposal') {
      if (!['reviewed', 'dismissed', 'inbox'].includes(String(body.state)))
        throw new SystemsInputError('Unknown review state')
      const version = typeof body.version === 'string' ? body.version : null
      if (
        body.state === 'reviewed' &&
        (!version || !db.prepare('SELECT 1 FROM system_versions WHERE id=?').get(version))
      )
        throw new SystemsInputError('Link reviewed rules to a published system first')
      db.prepare('UPDATE research_proposals SET state=?,version_id=? WHERE id=?').run(
        String(body.state),
        version,
        String(body.id)
      )
      return { status: 'saved' }
    }
    if (body.action === 'evaluate') {
      const v = db.prepare('SELECT * FROM system_versions WHERE id=?').get(String(body.version))
      if (!v) throw new SystemsInputError('Choose a system')
      const p = db.prepare('SELECT * FROM research_policies ORDER BY id DESC LIMIT 1').get()!
      const existing = db
        .prepare('SELECT * FROM discovery_trials WHERE id=?')
        .get(String(body.requestId))
      if (existing) {
        if (existing.version_id !== v.id)
          throw new SystemsInputError('Request identifier already used')
        return { status: existing.status, id: existing.id }
      }
      if (
        db
          .prepare(
            "SELECT 1 FROM discovery_trials WHERE version_id=? AND status IN ('queued','running')"
          )
          .get(String(v.id))
      )
        throw new SystemsInputError('This system already has a pending evaluation')
      const id = String(body.requestId)
      if (!/^[A-Za-z0-9_-]{1,120}$/.test(id))
        throw new SystemsInputError('Request identifier required')
      db.prepare(
        'INSERT OR IGNORE INTO discovery_batches(id,created_at,updated_at) VALUES (?,?,?)'
      ).run('manual-' + id, at, at)
      db.prepare(
        "INSERT OR IGNORE INTO discovery_trials(id,batch_id,version_id,asset,policy_id,budget,created_at,source) VALUES (?,?,?,?,?,?,?,'operator')"
      ).run(
        id,
        'manual-' + id,
        String(v.id),
        String(v.asset),
        Number(p.id),
        v.asset === 'bitcoin' ? String(p.sleeve) : '300',
        at
      )
      return { status: 'queued', id }
    }
    throw new SystemsInputError('Unknown research action')
  })
}

export function systemDetail(id: string) {
  if (!/^[A-Za-z0-9_-]{1,120}$/.test(id)) throw new SystemsInputError('Invalid system identifier')
  return researchDatabase(false, (db) => {
    const v = db.prepare('SELECT * FROM system_versions WHERE id=?').get(id)
    if (!v) throw new SystemsInputError('System unavailable')
    const lineage = db.prepare('SELECT * FROM research_lineage WHERE version_id=?').get(id)
    return {
      ...v,
      config: parsed(v.config_json),
      lineage: lineage ? { ...lineage, changes: parsed(lineage.changes_json) } : null,
      trials: db
        .prepare(
          'SELECT * FROM discovery_trials WHERE version_id=? ORDER BY created_at DESC LIMIT 20'
        )
        .all(id)
        .map(({ result_json, ...r }) => ({ ...r, result: parsed(result_json) })),
      allocation: db.prepare('SELECT * FROM btc_allocations WHERE version_id=?').get(id) || null,
      authorization:
        db.prepare('SELECT * FROM paper_authorizations WHERE version_id=?').get(id) || null,
      orders: db
        .prepare(
          'SELECT id,side,quantity,status,filled_qty,filled_notional,created_at,reason FROM btc_orders WHERE version_id=? ORDER BY created_at DESC LIMIT 30'
        )
        .all(id),
    }
  })
}

export function evaluationDetail(id: string) {
  if (!/^[A-Za-z0-9_-]{1,120}$/.test(id))
    throw new SystemsInputError('Invalid evaluation identifier')
  return researchDatabase(false, (db) => {
    const row = db
      .prepare(
        'SELECT t.*,v.config_json,v.config_sha256,d.manifest_json,d.sha256 AS dataset_sha256 FROM discovery_trials t JOIN system_versions v ON v.id=t.version_id LEFT JOIN system_datasets d ON d.id=t.dataset_id WHERE t.id=?'
      )
      .get(id)
    if (!row) throw new SystemsInputError('Evaluation unavailable')
    return {
      ...row,
      result: parsed(row.result_json),
      config: parsed(row.config_json),
      manifest: parsed(row.manifest_json),
      scenarios: db
        .prepare('SELECT * FROM discovery_scenarios WHERE trial_id=? ORDER BY window_index,profile')
        .all(id)
        .map(({ result_json, ...s }) => ({ ...s, result: parsed(result_json) })),
    }
  })
}
