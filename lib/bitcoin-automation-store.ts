import 'server-only'
import { createHash, randomUUID } from 'node:crypto'
import { researchDatabase } from './research-store'
import { SystemsInputError } from './systems-store'

export const bitcoinTimeframes = [
  '1Min',
  '5Min',
  '15Min',
  '1Hour',
  '4Hour',
  '1Day',
  '1Week',
  '1Month',
]
const protocol = 'bitcoin-automation-v2'
const canonical = (value: Record<string, unknown>) =>
  JSON.stringify(value, Object.keys(value).sort())

export function readBitcoinAutomation() {
  return researchDatabase(false, (db) => ({
    versions: db
      .prepare(
        `SELECT v.*,n.enrolled_at,n.approved_at,n.paused,n.active,q.status,q.reason,q.next_review_at,q.pass_streak,
      qe.cutoff AS evidence_cutoff,qe.expires_at AS evidence_expires_at,
      a.budget,a.cash,a.quantity,a.risk_paused,a.exit_due_at,a.last_decision_at,a.state_json AS paper_state_json
      FROM system_versions v LEFT JOIN btc_enrollments n ON n.version_id=v.id
      LEFT JOIN btc_qualifications q ON q.version_id=v.id LEFT JOIN btc_allocations a ON a.version_id=v.id
      LEFT JOIN btc_evaluations qe ON qe.id=q.evaluation_id
      WHERE json_extract(v.config_json,'$.protocol')=? ORDER BY v.created_at DESC`
      )
      .all(protocol),
    account: db.prepare('SELECT * FROM btc_accounts LIMIT 1').get() || null,
    evaluations: db
      .prepare(
        `SELECT e.*,(SELECT COUNT(*) FROM btc_scenarios s WHERE s.evaluation_id=e.id AND s.reused=1) AS cached
      FROM btc_evaluations e WHERE e.id IN (SELECT id FROM btc_evaluations ORDER BY created_at DESC LIMIT 20)
      OR e.id IN (SELECT evaluation_id FROM btc_orders ORDER BY created_at DESC LIMIT 50)
      ORDER BY e.created_at DESC`
      )
      .all(),
    orders: db.prepare('SELECT * FROM btc_orders ORDER BY created_at DESC LIMIT 50').all(),
    commands: db
      .prepare('SELECT * FROM btc_control_commands ORDER BY created_at DESC LIMIT 10')
      .all(),
    health: db
      .prepare('SELECT * FROM btc_health ORDER BY (error IS NOT NULL) DESC,at DESC LIMIT 50')
      .all(),
    forward: db
      .prepare(
        'SELECT version_id,MIN(at) AS started_at,MAX(at) AS latest_at,COUNT(DISTINCT substr(at,1,10)) AS days FROM btc_forward GROUP BY version_id'
      )
      .all(),
    fees: db.prepare('SELECT * FROM btc_fees ORDER BY captured_at DESC LIMIT 30').all(),
  }))
}

export function writeBitcoinAutomation(body: Record<string, unknown>) {
  const at = new Date().toISOString()
  return researchDatabase(true, (db) => {
    db.exec('BEGIN IMMEDIATE')
    try {
      let id = randomUUID() as string
      const action = body.action
      if (action === 'create') {
        const config = {
          asset: 'bitcoin',
          template: body.template || 'trend',
          fast: Number(body.fast ?? 20),
          slow: Number(body.slow ?? 100),
          entry: Number(body.entry ?? 55),
          exit: Number(body.exit ?? 20),
          allocation: Number(body.allocation ?? 0.5),
          timeframe: body.timeframe || '1Hour',
          holding_count: Number(body.holding_count ?? 7),
          holding_unit: body.holding_unit || 'days',
          protocol,
        }
        if (
          !['trend', 'breakout'].includes(String(config.template)) ||
          !bitcoinTimeframes.includes(String(config.timeframe))
        )
          throw new SystemsInputError('Choose a supported system and timeframe.')
        if (
          [config.fast, config.slow, config.entry, config.exit].some(
            (v) => !Number.isInteger(v) || v < 5 || v > 250
          ) ||
          config.fast >= config.slow ||
          config.exit >= config.entry
        )
          throw new SystemsInputError(
            'Lookbacks must be 5–250; fast and exit must be shorter than slow and entry.'
          )
        if (
          !Number.isFinite(config.allocation) ||
          config.allocation < 0.05 ||
          config.allocation > 0.5
        )
          throw new SystemsInputError('Position size must be 5–50% of the system’s budget.')
        const limits: Record<string, number> = {
          minutes: 525600,
          hours: 8760,
          days: 365,
          weeks: 52,
          months: 12,
        }
        if (
          !Number.isInteger(config.holding_count) ||
          config.holding_count < 1 ||
          !limits[String(config.holding_unit)] ||
          config.holding_count > limits[String(config.holding_unit)]
        )
          throw new SystemsInputError(
            'Choose a maximum holding period of one minute through 12 months.'
          )
        const hypothesis = typeof body.hypothesis === 'string' ? body.hypothesis.trim() : ''
        if (!hypothesis || hypothesis.length > 2000)
          throw new SystemsInputError('Describe the hypothesis in 1–2000 characters.')
        id = createHash('sha256')
          .update(canonical({ engine: protocol, ...config }))
          .digest('hex')
        db.prepare('INSERT OR IGNORE INTO system_versions VALUES (?,?,?,?,?,?,?)').run(
          id,
          'bitcoin',
          String(config.template),
          canonical(config),
          id,
          at,
          hypothesis
        )
      } else if (['enroll', 'approve', 'pause', 'resume', 'retire'].includes(String(action))) {
        id = String(body.version || '')
        if (
          !db
            .prepare(
              "SELECT 1 FROM system_versions WHERE id=? AND json_extract(config_json,'$.protocol')=?"
            )
            .get(id, protocol)
        )
          throw new SystemsInputError('Choose a Bitcoin automation version.')
        if (action === 'enroll') {
          if (
            !db.prepare('SELECT 1 FROM btc_enrollments WHERE version_id=? AND active=1').get(id) &&
            Number(
              db.prepare('SELECT COUNT(*) AS n FROM btc_enrollments WHERE active=1').get()?.n
            ) >= 5
          )
            throw new SystemsInputError(
              'Maximum five enrolled versions. Keep research and execution bounded.'
            )
          db.prepare(
            'INSERT INTO btc_enrollments(version_id,enrolled_at) VALUES (?,?) ON CONFLICT(version_id) DO UPDATE SET active=1,paused=0'
          ).run(id, at)
        } else {
          if (!db.prepare('SELECT 1 FROM btc_enrollments WHERE version_id=? AND active=1').get(id))
            throw new SystemsInputError('Start research collection first.')
          if (action === 'retire') {
            if (db.prepare('SELECT 1 FROM btc_allocations WHERE version_id=?').get(id))
              throw new SystemsInputError(
                'Remove this version from the funding plan before retiring research.'
              )
            db.prepare('UPDATE btc_enrollments SET active=0,paused=1 WHERE version_id=?').run(id)
            db.prepare(
              "UPDATE btc_qualifications SET status='suspended',reason='Research retired',pass_streak=0,failed_once=1 WHERE version_id=?"
            ).run(id)
            db.prepare(
              "UPDATE btc_evaluations SET status='canceled' WHERE version_id=? AND status IN ('queued','running')"
            ).run(id)
          } else if (action === 'approve') {
            if (body.confirmation !== id)
              throw new SystemsInputError(
                'Type the version ID to approve automatic paper entries when qualified.'
              )
            db.prepare(
              'UPDATE btc_enrollments SET approved_at=COALESCE(approved_at,?) WHERE version_id=?'
            ).run(at, id)
          } else
            db.prepare('UPDATE btc_enrollments SET paused=? WHERE version_id=?').run(
              action === 'pause' ? 1 : 0,
              id
            )
        }
      } else if (action === 'fund' || action === 'reactivate') {
        if (
          body.confirmation !==
          (action === 'fund' ? 'FUND BITCOIN PAPER' : 'REACTIVATE BITCOIN PAPER')
        )
          throw new SystemsInputError('Enter the confirmation phrase shown in the funding panel.')
        const versions = body.versions
        if (
          action === 'fund' &&
          (!Array.isArray(versions) ||
            versions.length < 1 ||
            versions.length > 5 ||
            new Set(versions).size !== versions.length ||
            versions.some(
              (v) =>
                typeof v !== 'string' ||
                !db
                  .prepare(
                    'SELECT 1 FROM btc_enrollments WHERE version_id=? AND active=1 AND approved_at IS NOT NULL'
                  )
                  .get(v)
            ))
        )
          throw new SystemsInputError('Select one to five approved versions.')
        if (
          Number(
            db.prepare("SELECT COUNT(*) AS n FROM btc_control_commands WHERE status='queued'").get()
              ?.n
          ) >= 5
        )
          throw new SystemsInputError('Wait for pending account commands to finish.')
        db.prepare(
          'INSERT INTO btc_control_commands(id,action,payload_json,created_at) VALUES (?,?,?,?)'
        ).run(id, action, JSON.stringify({ versions: versions || [] }), at)
      } else throw new SystemsInputError('Unsupported Bitcoin automation action.')
      db.prepare('INSERT INTO system_audit(at,action,entity_id,payload_json) VALUES (?,?,?,?)').run(
        at,
        `bitcoin_${action}`,
        id,
        JSON.stringify({ source: 'operator-ui' })
      )
      db.exec('COMMIT')
      return { id }
    } catch (error) {
      db.exec('ROLLBACK')
      throw error
    }
  })
}
