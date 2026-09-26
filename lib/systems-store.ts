import 'server-only'
import { createHash, randomUUID } from 'node:crypto'
import { researchDatabase } from './research-store'

export class SystemsInputError extends Error {}
export type AssetScope = 'stocks' | 'bitcoin'
function canonical(value: Record<string, unknown>) {
  return JSON.stringify(value, Object.keys(value).sort())
}
function string(value: unknown, name: string, max = 200) {
  if (typeof value !== 'string' || !value.trim() || value.length > max)
    throw new SystemsInputError(`Invalid ${name}.`)
  return value.trim()
}
function audit(
  db: Parameters<Parameters<typeof researchDatabase>[1]>[0],
  action: string,
  entity: string,
  payload: unknown
) {
  db.prepare('INSERT INTO system_audit(at,action,entity_id,payload_json) VALUES (?,?,?,?)').run(
    new Date().toISOString(),
    action,
    entity,
    JSON.stringify(payload)
  )
}
export function readSystems(asset: AssetScope) {
  return researchDatabase(false, (db) => ({
    versions: db
      .prepare(
        "SELECT * FROM system_versions WHERE asset=? AND json_extract(config_json,'$.protocol') IS NULL ORDER BY created_at DESC"
      )
      .all(asset),
    datasets: db
      .prepare(
        'SELECT id,asset,manifest_json,created_at FROM system_datasets WHERE asset=? ORDER BY created_at DESC'
      )
      .all(asset),
    runs: db
      .prepare(
        'SELECT r.* FROM system_runs r JOIN system_versions v ON v.id=r.version_id WHERE v.asset=? ORDER BY r.created_at DESC LIMIT 10'
      )
      .all(asset),
    deployments: db
      .prepare(
        'SELECT d.*,v.template FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE v.asset=? ORDER BY d.started_at DESC'
      )
      .all(asset),
    observations: db
      .prepare(
        'SELECT o.* FROM system_observations o JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE v.asset=? ORDER BY o.observed_at DESC LIMIT 30'
      )
      .all(asset),
    orders: db
      .prepare(
        'SELECT o.* FROM system_orders o JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE v.asset=? ORDER BY o.created_at DESC LIMIT 100'
      )
      .all(asset),
    commands: db
      .prepare(
        'SELECT c.* FROM system_commands c JOIN system_deployments d ON d.id=c.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE v.asset=? ORDER BY c.created_at DESC LIMIT 20'
      )
      .all(asset),
  }))
}
export function readBitcoin() {
  return researchDatabase(false, (db) => ({
    market:
      db
        .prepare(
          "SELECT * FROM bitcoin_observations WHERE kind='market' ORDER BY observed_at DESC LIMIT 1"
        )
        .get() || null,
    network:
      db
        .prepare(
          "SELECT * FROM bitcoin_observations WHERE kind='network' ORDER BY observed_at DESC LIMIT 1"
        )
        .get() || null,
    errors: db
      .prepare(
        "SELECT * FROM bitcoin_observations WHERE kind='error' ORDER BY observed_at DESC LIMIT 5"
      )
      .all(),
    addresses: db
      .prepare(
        "SELECT w.*,o.payload_json FROM bitcoin_watch_addresses w LEFT JOIN bitcoin_observations o ON o.id=(SELECT id FROM bitcoin_observations WHERE kind='address' AND subject=w.address ORDER BY observed_at DESC LIMIT 1) ORDER BY w.added_at"
      )
      .all(),
    requests: db
      .prepare('SELECT * FROM bitcoin_watch_requests ORDER BY created_at DESC LIMIT 20')
      .all(),
    transactions: db
      .prepare('SELECT * FROM bitcoin_transactions ORDER BY observed_at DESC LIMIT 50')
      .all(),
  }))
}
export function writeSystems(body: Record<string, unknown>) {
  const action = string(body.action, 'action')
  const at = new Date().toISOString()
  return researchDatabase(true, (db) => {
    db.exec('BEGIN IMMEDIATE')
    try {
      let id = randomUUID() as string
      if (action === 'create') {
        const asset = body.asset
        if (asset !== 'stocks' && asset !== 'bitcoin')
          throw new SystemsInputError('Choose Stocks or Bitcoin.')
        if (body.template !== 'trend' && body.template !== 'breakout')
          throw new SystemsInputError('Choose a supported template.')
        const config = {
          asset,
          template: body.template,
          fast: Number(body.fast ?? 20),
          slow: Number(body.slow ?? 100),
          entry: Number(body.entry ?? 55),
          exit: Number(body.exit ?? 20),
          allocation: Number(body.allocation ?? 0.5),
        }
        if (
          [config.fast, config.slow, config.entry, config.exit].some(
            (v) => !Number.isInteger(v) || v < 5 || v > 250
          ) ||
          config.fast >= config.slow ||
          config.exit >= config.entry
        )
          throw new SystemsInputError(
            'Lookbacks must be 5–250; fast/exit must be shorter than slow/entry.'
          )
        if (
          !Number.isFinite(config.allocation) ||
          config.allocation < 0.05 ||
          config.allocation > 1
        )
          throw new SystemsInputError('Allocation must be 5–100%.')
        const hypothesis = string(body.hypothesis, 'hypothesis', 2000)
        id = createHash('sha256')
          .update(canonical({ engine: 'cash-replay-v1', ...config }))
          .digest('hex')
        db.prepare('INSERT OR IGNORE INTO system_versions VALUES (?,?,?,?,?,?,?)').run(
          id,
          asset,
          config.template,
          canonical(config),
          id,
          at,
          hypothesis
        )
      } else if (action === 'backtest') {
        const version = string(body.version, 'version')
        const dataset = string(body.dataset, 'dataset')
        const config = db.prepare('SELECT config_json FROM system_versions WHERE id=?').get(version)
        if (config && JSON.parse(String(config.config_json)).protocol)
          throw new SystemsInputError(
            'Version-two Bitcoin systems use scheduled scenario evaluations.'
          )
        const matching = db
          .prepare(
            'SELECT 1 FROM system_versions v JOIN system_datasets d ON d.asset=v.asset WHERE v.id=? AND d.id=?'
          )
          .get(version, dataset)
        if (!matching) throw new SystemsInputError('Choose a version and matching dataset.')
        if (
          Number(
            db
              .prepare("SELECT COUNT(*) AS n FROM system_runs WHERE status IN ('queued','running')")
              .get()?.n
          ) >= 10
        )
          throw new SystemsInputError('The research queue is full.')
        db.prepare(
          "INSERT INTO system_runs(id,version_id,dataset_id,status,created_at) VALUES (?,?,?,'queued',?)"
        ).run(id, version, dataset, at)
      } else if (action === 'cancel') {
        id = string(body.run, 'run')
        db.prepare(
          "UPDATE system_runs SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'canceled' ELSE status END WHERE id=? AND status IN ('queued','running')"
        ).run(id)
      } else if (action === 'shadow') {
        const version = string(body.version, 'version')
        const config = db.prepare('SELECT config_json FROM system_versions WHERE id=?').get(version)
        if (config && JSON.parse(String(config.config_json)).protocol)
          throw new SystemsInputError('Start collection from Bitcoin automation for this version.')
        if (!db.prepare('SELECT 1 FROM system_versions WHERE id=?').get(version))
          throw new SystemsInputError('Unknown version.')
        const asset = db.prepare('SELECT asset FROM system_versions WHERE id=?').get(version)?.asset
        if (
          Number(
            db
              .prepare(
                "SELECT COUNT(*) AS n FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE v.asset=? AND d.mode='shadow'"
              )
              .get(String(asset))?.n
          ) >= 4
        )
          throw new SystemsInputError('Maximum four simultaneous shadow systems per asset.')
        if (db.prepare('SELECT 1 FROM system_deployments WHERE version_id=?').get(version))
          throw new SystemsInputError('This version already has a deployment.')
        db.prepare(
          "INSERT INTO system_deployments(id,version_id,mode,started_at) VALUES (?,?,'shadow',?)"
        ).run(id, version, at)
      } else if (['activate', 'pause', 'resume'].includes(action)) {
        const deployment = string(body.deployment, 'deployment')
        if (body.confirmation !== deployment)
          throw new SystemsInputError('Type the full deployment ID to confirm.')
        if (!db.prepare('SELECT 1 FROM system_deployments WHERE id=?').get(deployment))
          throw new SystemsInputError('Unknown deployment.')
        db.prepare(
          'INSERT INTO system_commands(id,deployment_id,action,confirmation,created_at) VALUES (?,?,?,?,?)'
        ).run(id, deployment, action, deployment, at)
      } else if (action === 'watch') {
        const address = string(body.address, 'address', 90)
        const label = typeof body.label === 'string' ? body.label.trim().slice(0, 120) : ''
        if (!/^(bc1|BC1|1|3)[a-zA-Z0-9]+$/.test(address))
          throw new SystemsInputError('Enter a Bitcoin mainnet address.')
        if (
          Number(
            db
              .prepare(
                "SELECT (SELECT COUNT(*) FROM bitcoin_watch_addresses)+(SELECT COUNT(*) FROM bitcoin_watch_requests WHERE status='queued') AS n"
              )
              .get()?.n
          ) >= 20
        )
          throw new SystemsInputError('Maximum 20 watched addresses.')
        db.prepare(
          'INSERT INTO bitcoin_watch_requests(id,address,label,created_at) VALUES (?,?,?,?)'
        ).run(id, address, label, at)
      } else if (action === 'unwatch') {
        id = string(body.address, 'address', 90)
        db.prepare('DELETE FROM bitcoin_watch_addresses WHERE address=?').run(id)
      } else {
        throw new SystemsInputError('Unsupported action.')
      }
      audit(db, action, id, { source: 'operator-ui' })
      db.exec('COMMIT')
      return { id }
    } catch (error) {
      db.exec('ROLLBACK')
      throw error
    }
  })
}
