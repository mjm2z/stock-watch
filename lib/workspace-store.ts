import 'server-only'
import { randomUUID, createHash } from 'node:crypto'
import { researchDatabase } from './research-store'
import { SystemsInputError } from './systems-store'
export type Asset = 'stocks' | 'bitcoin'
export function assetOf(value: unknown): Asset {
  if (value === 'stocks') return 'stocks'
  if (value === 'bitcoin' || value === 'crypto') return 'bitcoin'
  throw new SystemsInputError('Choose Stocks or Crypto.')
}
const parse = (value: unknown) => {
  try {
    return JSON.parse(String(value || '{}'))
  } catch {
    return {}
  }
}
function text(v: unknown, name: string, max = 120) {
  if (typeof v !== 'string' || !v.trim() || v.length > max)
    throw new SystemsInputError(`${name} is required (maximum ${max} characters).`)
  return v.trim()
}
function previewResult(result: Record<string, unknown>): Record<string, unknown> {
  for (const value of Object.values(result)) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const summary = value as Record<string, unknown>
      if (Array.isArray(summary.equity_curve)) {
        let peak = 0
        summary.equity_curve = summary.equity_curve.map((p) => {
          peak = Math.max(peak, Number(p.equity))
          return { ...p, drawdown: peak ? 100 * (Number(p.equity) / peak - 1) : 0 }
        })
      }
    }
  }

  const bounded = (v: unknown): unknown => {
    if (Array.isArray(v)) {
      const rows =
        v.length > 600
          ? Array.from({ length: 600 }, (_, i) => v[Math.floor((i * (v.length - 1)) / 599)])
          : v
      return rows.map(bounded)
    }
    if (v && typeof v === 'object')
      return Object.fromEntries(
        Object.entries(v).map(([k, x]) => [
          k,
          k === 'fills' && Array.isArray(x) ? x.slice(0, 200) : bounded(x),
        ])
      )
    return v
  }
  return {
    ...(bounded(result) as Record<string, unknown>),
    display_note:
      'Chart series are sampled to at most 600 observations; fills show the first 200. Complete saved runs are unchanged.',
  }
}
export function readWorkspace(asset: Asset) {
  return researchDatabase(false, (db) => {
    const versions = db
      .prepare(
        'SELECT v.*,COALESCE(d.archived,0) AS archived,d.draft_id,d.parent_version FROM system_versions v LEFT JOIN workspace_version_details d ON d.version_id=v.id WHERE v.asset=? ORDER BY v.created_at DESC LIMIT 500'
      )
      .all(asset)
      .map((v) => ({ ...v, config: parse(v.config_json) }))
    const drafts = db
      .prepare('SELECT * FROM workspace_drafts WHERE asset=? ORDER BY updated_at DESC LIMIT 500')
      .all(asset)
      .map((d) => ({ ...d, document: parse(d.document_json) }))
    const jobs = db
      .prepare(
        "SELECT j.*,c.status AS command_status,c.error AS command_error,rr.status AS run_status,rr.error AS run_error,rr.progress AS run_progress FROM workspace_jobs j LEFT JOIN system_commands c ON c.id=j.id LEFT JOIN system_runs rr ON rr.id=j.id WHERE json_extract(j.payload_json,'$.asset')=? ORDER BY j.created_at DESC LIMIT 60"
      )
      .all(asset)
      .map((j) => ({
        ...j,
        status: j.command_status || j.run_status || j.status,
        progress: j.run_progress ?? j.progress,
        error: j.command_error || j.run_error || j.error,
        result: parse(j.result_json),
      }))
    const runs = db
      .prepare(
        'SELECT r.* FROM system_runs r JOIN system_versions v ON v.id=r.version_id WHERE v.asset=? ORDER BY r.created_at DESC LIMIT 20'
      )
      .all(asset)
      .map(({ result_json, ...r }) => ({ ...r, result: previewResult(parse(result_json)) }))
    const deployments = db
      .prepare(
        'SELECT d.* FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE v.asset=?'
      )
      .all(asset)
    const qualifications =
      asset === 'bitcoin' ? db.prepare('SELECT * FROM btc_qualifications').all() : []
    const allocations = asset === 'bitcoin' ? db.prepare('SELECT * FROM btc_allocations').all() : []
    const enrollments = asset === 'bitcoin' ? db.prepare('SELECT * FROM btc_enrollments').all() : []
    return {
      asset,
      versions,
      drafts,
      jobs,
      runs,
      deployments,
      qualifications,
      allocations,
      enrollments,
      datasets: db
        .prepare(
          'SELECT id,asset,manifest_json,created_at FROM system_datasets WHERE asset=? ORDER BY created_at DESC LIMIT 30'
        )
        .all(asset)
        .map(({ manifest_json, ...d }) => ({ ...d, manifest: parse(manifest_json) })),
    }
  })
}
export function workspaceCommand(body: Record<string, unknown>) {
  return researchDatabase(true, (db) => {
    const action = text(body.action, 'Action', 30),
      asset = assetOf(body.asset),
      at = new Date().toISOString()
    if (action === 'save_draft') {
      const id = body.id ? text(body.id, 'Draft ID') : randomUUID(),
        name = text(body.name, 'System name')
      if (!body.document || typeof body.document !== 'object' || Array.isArray(body.document))
        throw new SystemsInputError('A rule document is required.')
      const doc = JSON.stringify(body.document)
      if (doc.length > 10000) throw new SystemsInputError('System is too large.')
      const existing = db.prepare('SELECT asset FROM workspace_drafts WHERE id=?').get(id)
      if (existing && existing.asset !== asset)
        throw new SystemsInputError('Draft asset cannot change.')
      db.prepare(
        'INSERT INTO workspace_drafts(id,name,asset,document_json,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,document_json=excluded.document_json,updated_at=excluded.updated_at'
      ).run(id, name, asset, doc, at)
      return { id, status: 'saved' }
    }
    if (action === 'archive_version') {
      const id = text(body.id, 'System version')
      if (!db.prepare('SELECT 1 FROM system_versions WHERE id=? AND asset=?').get(id, asset))
        throw new SystemsInputError('Unknown version.')
      if (
        db
          .prepare(
            "SELECT 1 FROM system_deployments WHERE version_id=? AND mode IN ('paper','paused')"
          )
          .get(id) ||
        db
          .prepare('SELECT 1 FROM btc_allocations WHERE version_id=? AND started_at IS NOT NULL')
          .get(id)
      )
        throw new SystemsInputError(
          'Paper-authorized systems remain visible; archiving cannot change trading authority.'
        )
      db.prepare(
        'INSERT INTO workspace_version_details(version_id,archived) VALUES (?,?) ON CONFLICT(version_id) DO UPDATE SET archived=excluded.archived'
      ).run(id, body.archived === false ? 0 : 1)
      return { id, status: 'saved' }
    }
    if (action === 'archive') {
      const id = text(body.id, 'Draft ID')
      db.prepare('UPDATE workspace_drafts SET archived=? WHERE id=? AND asset=?').run(
        body.archived === false ? 0 : 1,
        id,
        asset
      )
      return { id, status: 'saved' }
    }
    if (action === 'cancel') {
      const id = text(body.id, 'Job ID')
      db.prepare(
        "UPDATE workspace_jobs SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'canceled' ELSE status END WHERE id=? AND json_extract(payload_json,'$.asset')=? AND kind='backtest' AND status IN ('queued','running')"
      ).run(id, asset)
      db.prepare(
        "UPDATE system_runs SET cancel_requested=1 WHERE id=? AND version_id IN (SELECT id FROM system_versions WHERE asset=?) AND status IN ('queued','running')"
      ).run(id, asset)
      return { id, status: 'requested' }
    }
    if (!['publish', 'backtest', 'observe', 'start_paper', 'pause', 'resume'].includes(action))
      throw new SystemsInputError('Unknown command.')
    const id = text(body.requestId, 'Request ID'),
      version = body.version ? text(body.version, 'System version') : undefined
    if (!/^[A-Za-z0-9_-]{1,120}$/.test(id))
      throw new SystemsInputError('Invalid request identifier.')
    if (
      body.parentVersion &&
      !db
        .prepare('SELECT 1 FROM system_versions WHERE id=? AND asset=?')
        .get(String(body.parentVersion), asset)
    )
      throw new SystemsInputError('Unknown parent version.')
    if (
      body.parentRun &&
      !db
        .prepare('SELECT 1 FROM system_runs WHERE id=? AND version_id=?')
        .get(String(body.parentRun), String(body.parentVersion))
    )
      throw new SystemsInputError('Parent run must belong to the parent version.')
    if (
      version &&
      !db.prepare('SELECT id FROM system_versions WHERE id=? AND asset=?').get(version, asset)
    )
      throw new SystemsInputError('Unknown system version.')
    if (
      action === 'publish' &&
      !db
        .prepare('SELECT id FROM workspace_drafts WHERE id=? AND asset=?')
        .get(String(body.draft), asset)
    )
      throw new SystemsInputError('Save a draft first.')
    if (action !== 'publish' && !version) throw new SystemsInputError('Choose a published system.')
    if (['start_paper', 'resume'].includes(action) && body.confirmation !== version)
      throw new SystemsInputError('Confirm the exact system version.')
    if (action === 'backtest') {
      const start = Date.parse(String(body.start)),
        end = Date.parse(String(body.end))
      if (
        !Number.isFinite(start) ||
        !Number.isFinite(end) ||
        start >= end ||
        end > Date.now() ||
        start < Date.UTC(2016, 0, 1)
      )
        throw new SystemsInputError('Choose an available historical date range since 2016.')
      if (body.costMultiplier !== undefined && ![1, 2, 3].includes(Number(body.costMultiplier)))
        throw new SystemsInputError('Choose a supported cost stress.')
    }
    const frozen =
      action === 'publish'
        ? db
            .prepare(
              'SELECT name,document_json,published_version FROM workspace_drafts WHERE id=? AND asset=?'
            )
            .get(String(body.draft), asset)
        : undefined
    const payload = JSON.stringify({ ...body, asset, ...(frozen ? { snapshot: frozen } : {}) }),
      existing = db.prepare('SELECT payload_json FROM workspace_jobs WHERE id=?').get(id)
    if (
      existing &&
      JSON.stringify((({ snapshot, ...request }) => request)(parse(existing.payload_json))) !==
        JSON.stringify({ ...body, asset })
    )
      throw new SystemsInputError('Request identifier was already used for a different command.')
    if (
      !existing &&
      Number(
        db
          .prepare("SELECT count(*) AS n FROM workspace_jobs WHERE status IN ('queued','running')")
          .get()?.n
      ) > 30
    )
      throw new SystemsInputError('Research queue is full. Wait for a current job to finish.')
    db.prepare(
      'INSERT OR IGNORE INTO workspace_jobs(id,kind,payload_json,created_at) VALUES (?,?,?,?)'
    ).run(id, action, payload, at)
    return { id, status: 'queued' }
  })
}
export function chartRequest(range: string, startInput?: string | null, endInput?: string | null) {
  const days: Record<string, number> = {
    '1D': 1,
    '1W': 7,
    '1M': 30,
    '3M': 90,
    '6M': 183,
    '1Y': 365,
    ALL: 3650,
  }
  if (!days[range] && range !== 'custom') throw new SystemsInputError('Unknown chart range.')
  const end = new Date()
  end.setUTCSeconds(0, 0)
  const endAt = endInput ? new Date(endInput) : end
  const start = startInput
    ? new Date(startInput)
    : new Date(endAt.getTime() - days[range] * 86400000)
  if (
    !Number.isFinite(+start) ||
    !Number.isFinite(+endAt) ||
    start >= endAt ||
    +endAt > Date.now() ||
    +endAt - +start > 3660 * 86400000
  )
    throw new SystemsInputError('Choose an ordered range up to ten years.')
  const span = (+endAt - +start) / 86400000,
    frame = span <= 2 ? '5Min' : span <= 32 ? '1Hour' : span <= 190 ? '4Hour' : '1Day'
  // Daily charts do not need a new multi-year download every five minutes.
  if (!endInput)
    endAt.setUTCMinutes(frame === '1Day' ? 0 : Math.floor(endAt.getUTCMinutes() / 5) * 5, 0, 0)
  if (!startInput) start.setUTCMinutes(0, 0, 0)
  const payload = {
    asset: 'bitcoin',
    start: start.toISOString(),
    end: endAt.toISOString(),
    frame,
    range,
  }
  const key = createHash('sha256').update(JSON.stringify(payload)).digest('hex')
  return researchDatabase(true, (db) => {
    const cached = db
      .prepare('SELECT payload_json,updated_at FROM crypto_chart_cache WHERE key=?')
      .get(key)
    const job = db.prepare('SELECT status,error FROM workspace_jobs WHERE id=?').get('chart-' + key)
    if (!cached && !job)
      db.prepare(
        "INSERT INTO workspace_jobs(id,kind,payload_json,created_at) SELECT ?,?,?,? WHERE (SELECT COUNT(*) FROM workspace_jobs WHERE kind='chart' AND status IN ('queued','running'))<10"
      ).run('chart-' + key, 'chart', JSON.stringify({ ...payload, key }), new Date().toISOString())
    // Keep a recent matching window visible while its replacement is collected.
    // Custom dates require an exact match; never substitute a different interval.
    const previous =
      !cached && !startInput && !endInput && range !== 'custom'
        ? db
            .prepare(
              `SELECT c.payload_json FROM crypto_chart_cache c
          JOIN workspace_jobs j ON j.id='chart-' || c.key
          WHERE json_extract(j.payload_json,'$.range')=?
          AND json_extract(j.payload_json,'$.frame')=?
          AND datetime(c.updated_at)>datetime('now','-2 days')
          ORDER BY c.updated_at DESC LIMIT 1`
            )
            .get(range, frame)
        : undefined
    const fallback = previous ? parse(previous.payload_json) : null
    return cached
      ? { ...parse(cached.payload_json), status: 'ready' }
      : fallback?.bars?.length
        ? {
            ...fallback,
            status: 'ready',
            refreshing: !['failed', 'canceled'].includes(String(job?.status)),
            stale: true,
            error: job?.error || null,
          }
        : {
            status: job?.status || 'queued',
            error: job?.error || null,
            bars: [],
            provider: 'Alpaca US',
            ...payload,
          }
  })
}
