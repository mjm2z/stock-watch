import 'server-only'
import { researchDatabase } from './research-store'
import { SystemsInputError } from './systems-store'
export function readLean() {
  return researchDatabase(false, (db) => {
    const health = db.prepare('SELECT * FROM lean_runner_health WHERE id=1').get()
    return {
      health: health
        ? {
            updatedAt: health.updated_at,
            ...JSON.parse(String(health.payload_json)),
            stale: Date.now() - Date.parse(String(health.updated_at)) > 60000,
          }
        : { configured: false, healthy: false },
      runs: db
        .prepare(
          'SELECT id,version_id,dataset_id,status,created_at,started_at,updated_at,finished_at,cancel_requested,error FROM lean_comparisons ORDER BY created_at DESC LIMIT 50'
        )
        .all(),
    }
  })
}
export function writeLean(body: Record<string, unknown>) {
  const id = String(body.id || '')
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id))
    throw new SystemsInputError('Invalid comparison identifier')
  return researchDatabase(true, (db) => {
    db.exec('BEGIN IMMEDIATE')
    try {
      const existing = db.prepare('SELECT * FROM lean_comparisons WHERE id=?').get(id)
      if (body.action === 'cancel') {
        if (!existing) throw new SystemsInputError('Comparison not found')
        db.prepare(
          "UPDATE lean_comparisons SET cancel_requested=1 WHERE id=? AND status NOT IN ('complete','failed','canceled')"
        ).run(id)
      } else if (body.action === 'create') {
        if (existing) {
          if (existing.version_id !== body.version || existing.dataset_id !== body.dataset)
            throw new SystemsInputError('Identifier belongs to a different comparison')
        } else {
          const health = db.prepare('SELECT * FROM lean_runner_health WHERE id=1').get()
          const state = health ? JSON.parse(String(health.payload_json)) : {}
          if (
            !state.configured ||
            !state.healthy ||
            Date.now() - Date.parse(String(health?.updated_at)) > 60000
          )
            throw new SystemsInputError('LEAN runner is unavailable or not configured')
          const version = db
            .prepare('SELECT * FROM system_versions WHERE id=?')
            .get(String(body.version || ''))
          const dataset = db
            .prepare('SELECT * FROM system_datasets WHERE id=?')
            .get(String(body.dataset || ''))
          const config = version ? JSON.parse(String(version.config_json)) : {}
          const manifest = dataset ? JSON.parse(String(dataset.manifest_json)) : {}
          if (config.asset !== 'bitcoin' || config.template !== 'trend' || config.protocol)
            throw new SystemsInputError('Choose an original Bitcoin trend version')
          if (dataset?.asset !== 'bitcoin' || manifest.timeframe !== '1Hour')
            throw new SystemsInputError('Choose an hourly Bitcoin dataset')
          if (
            Number(
              db
                .prepare(
                  "SELECT count(*) n FROM lean_comparisons WHERE status NOT IN ('complete','failed','canceled')"
                )
                .get()!.n
            ) >= 5
          )
            throw new SystemsInputError('Comparison queue is full')
          const now = new Date().toISOString()
          db.prepare(
            "INSERT INTO lean_comparisons(id,version_id,dataset_id,status,created_at,updated_at) VALUES (?,?,?,'queued',?,?)"
          ).run(id, String(body.version), String(body.dataset), now, now)
        }
      } else throw new SystemsInputError('Unknown LEAN action')
      db.prepare('INSERT INTO system_audit(at,action,entity_id,payload_json) VALUES (?,?,?,?)').run(
        new Date().toISOString(),
        `lean_${body.action}`,
        id,
        JSON.stringify({ version: body.version, dataset: body.dataset })
      )
      db.exec('COMMIT')
      return { id }
    } catch (error) {
      db.exec('ROLLBACK')
      throw error
    }
  })
}
