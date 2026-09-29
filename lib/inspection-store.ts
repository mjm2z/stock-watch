import 'server-only'
import { DatabaseSync } from 'node:sqlite'
import { dirname, join } from 'node:path'
import type { ChartEvent } from './chart-events'
import { researchDatabase } from './research-store'
export type Layer = 'orders' | 'positions' | 'protections' | 'systems' | 'activity' | 'preview'
export type ChartLevel = {
  id: string
  layer: Layer
  price?: number
  label: string
  asset: string
  symbol: string
  account: string
  owner: string
  asOf: string
  validFrom?: string
  source: string
  basis: 'raw'
  evidence: unknown
}
export type ActivityRow = {
  id: string
  asset: string
  symbol: string
  account: string
  owner: string
  entity: string
  kind: string
  status: string
  at: string
  evidence: unknown
}
const parse = (x: unknown) => {
  try {
    return JSON.parse(String(x || '{}'))
  } catch {
    return {}
  }
}
function manualRead<T>(fn: (db: DatabaseSync) => T) {
  const path =
    process.env.STOCK_WATCH_MANUAL_DATABASE ||
    join(
      dirname(process.env.STOCK_WATCH_DATABASE_PATH || '/var/lib/stock-watch/stock-watch.db'),
      'manual-paper.db'
    )
  const db = new DatabaseSync(path, { readOnly: true })
  try {
    db.exec('PRAGMA busy_timeout=200')
    return fn(db)
  } finally {
    db.close()
  }
}
export function inspection(query: URLSearchParams) {
  const asset = query.get('asset') === 'bitcoin' ? 'bitcoin' : 'stocks'
  const symbol = (query.get('symbol') || (asset === 'bitcoin' ? 'BTC/USD' : 'SPY')).toUpperCase()
  if (!(asset === 'bitcoin' ? symbol === 'BTC/USD' : /^[A-Z][A-Z0-9.-]{0,14}$/.test(symbol)))
    throw Error('Invalid instrument')
  const scope = query.get('scope') || 'manual'
  if (!['manual', 'automated', 'scanner'].includes(scope)) throw Error('Invalid account scope')
  const levels: ChartLevel[] = [],
    unavailable: string[] = [],
    previewEvents: ChartEvent[] = []
  const previews: any[] = [],
    systems: any[] = []
  const asOf = new Date().toISOString()
  function level(
    row: any,
    layer: Layer,
    price: unknown,
    label: string,
    owner: string,
    source: string,
    suffix = ''
  ) {
    levels.push({
      id: `${scope}:${row.id || row.version_id}:${suffix || layer}`,
      layer,
      ...(Number(price) > 0 && Number.isFinite(Number(price)) ? { price: Number(price) } : {}),
      label,
      asset,
      symbol,
      account: row.account_id || scope,
      owner,
      asOf: row.updated
        ? new Date(row.updated * 1000).toISOString()
        : row.updated_at || row.checked_at || asOf,
      validFrom: row.created
        ? new Date(row.created * 1000).toISOString()
        : row.created_at || row.entry_at,
      source,
      basis: 'raw',
      evidence: row,
    })
  }
  try {
    if (scope === 'manual')
      manualRead((db) => {
        const rows: any[] = db
          .prepare(
            'SELECT * FROM instructions WHERE asset=? AND symbol=? ORDER BY created DESC LIMIT 200'
          )
          .all(asset, symbol)
        for (const row of rows) {
          const req = parse(row.request)
          if (!['filled', 'canceled', 'expired', 'rejected'].includes(row.status)) {
            level(
              row,
              'orders',
              req.limit_price,
              `${row.side} ${req.notional ? '$' + req.notional : Math.max(0, Number(row.qty) - Number(row.filled_qty))} · ${req.type} · ${row.status}`,
              'manual',
              'Alpaca broker instruction'
            )
            if (req.stop_price)
              level(
                row,
                'protections',
                req.stop_price,
                `${req.type} broker trigger`,
                'manual',
                'Alpaca broker instruction',
                'stop'
              )
            if (row.condition)
              level(
                row,
                'protections',
                row.threshold,
                `Local ${row.condition} trigger · host required`,
                'manual',
                asset === 'bitcoin'
                  ? 'Coinbase observation trigger; Alpaca validation'
                  : 'Alpaca IEX trigger',
                'trigger'
              )
          }
        }
        const plans: any[] = db
          .prepare(
            "SELECT p.*,i.account_id,i.updated,i.symbol FROM protective_plans p JOIN instructions i ON i.id=p.parent WHERE i.asset=? AND i.symbol=? AND p.status NOT IN ('closed','canceled') LIMIT 100"
          )
          .all(asset, symbol)
        for (const row of plans)
          for (const key of ['stop_loss', 'take_profit'])
            if (row[key])
              level(
                row,
                'protections',
                row[key],
                `${key.replace('_', ' ')} · ${row.status} · local, not OCO`,
                'manual',
                'Local protective plan; actual fill coverage required',
                key
              )
        // Lifetime attribution, not just the display's last 200 orders. Quantity only:
        // no fictitious average basis from netting historical buys and sells.
        const totals: any = db
          .prepare(
            "SELECT account_id,SUM(CASE side WHEN 'buy' THEN CAST(filled_qty AS REAL) ELSE -CAST(filled_qty AS REAL) END) quantity FROM instructions WHERE asset=? AND symbol=? GROUP BY account_id"
          )
          .get(asset, symbol)
        if (totals?.quantity > 0) {
          const snap: any = db.prepare("SELECT * FROM snapshots WHERE asset='combined'").get()
          const snapshot = parse(snap?.payload)
          const position =
            snapshot.performance?.cash_reconciled &&
            snapshot.positions?.find(
              (p: any) => p.symbol.replace('/', '') === symbol.replace('/', '')
            )
          level(
            { ...totals, id: 'owned', updated: snap?.at, snapshot: position || null },
            'positions',
            position?.avg_entry_price,
            `${position?.qty || totals.quantity} units · ${position ? 'broker average entry' : 'basis unavailable'}`,
            'manual',
            position ? 'Reconciled Alpaca position snapshot' : 'Durable manual fill attribution'
          )
        }
      })
    else
      researchDatabase(false, (db) => {
        if (scope === 'automated' && asset === 'bitcoin') {
          for (const row of db
            .prepare(
              "SELECT * FROM btc_orders WHERE status NOT IN ('filled','canceled','expired','rejected') ORDER BY updated_at DESC LIMIT 100"
            )
            .all() as any[]) {
            const response = parse(row.response_json)
            level(
              row,
              'orders',
              response.limit_price,
              `${row.side} ${Math.max(0, Number(row.quantity) - Number(row.filled_qty))} · ${row.status}`,
              row.version_id,
              'Alpaca; reference price is not an executable limit'
            )
          }
          for (const row of db
            .prepare(
              'SELECT a.*,v.config_json FROM btc_allocations a JOIN system_versions v ON v.id=a.version_id WHERE CAST(a.quantity AS REAL)>0 LIMIT 100'
            )
            .all() as any[]) {
            level(
              row,
              'positions',
              row.entry_price,
              `${row.quantity} BTC · system position`,
              row.version_id,
              'Automated allocation ledger'
            )
            const config = parse(row.config_json)
            for (const key of ['stop_loss', 'take_profit'])
              if (Number(row.entry_price) > 0 && Number(config[key]) > 0)
                level(
                  row,
                  'protections',
                  Number(row.entry_price) *
                    (1 + (key === 'stop_loss' ? -1 : 1) * Number(config[key])),
                  `${key} · configured local risk threshold`,
                  row.version_id,
                  'Immutable system configuration; not a broker order',
                  key
                )
          }
        } else if (scope === 'scanner' && asset === 'stocks') {
          for (const row of db
            .prepare(
              "SELECT o.*,i.symbol FROM paper_orders o JOIN signals s ON s.id=o.signal_id JOIN instruments i ON i.id=s.instrument_id WHERE i.symbol=? AND o.status NOT IN ('filled','canceled','rejected') ORDER BY o.updated_at DESC LIMIT 100"
            )
            .all(symbol) as any[])
            level(
              { ...row, account_id: 'automated-stocks' },
              'orders',
              row.limit_price,
              `${row.side} $${row.notional_usd} · ${row.order_type} · ${row.status}`,
              'legacy-scanner',
              'Legacy broker entry instruction'
            )
          for (const row of db
            .prepare(
              "SELECT l.*,i.symbol FROM paper_trade_lots l JOIN instruments i ON i.id=l.instrument_id WHERE i.symbol=? AND l.status IN ('open','closing') LIMIT 100"
            )
            .all(symbol) as any[])
            level(
              row,
              'positions',
              row.entry_price,
              `${row.entry_quantity} shares · ${row.status} · exit ${row.target_exit_at || 'unavailable'}`,
              'legacy-scanner',
              'Legacy lot ledger'
            )
        } else {
          for (const row of db
            .prepare(
              "SELECT d.id,d.account_id,d.version_id,MAX(o.updated_at) updated_at,SUM(CASE o.side WHEN 'buy' THEN CAST(o.filled_qty AS REAL) ELSE -CAST(o.filled_qty AS REAL) END) quantity FROM system_orders o JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE v.asset=? AND o.symbol=? GROUP BY d.id HAVING quantity>0 LIMIT 100"
            )
            .all(asset, symbol) as any[])
            level(
              row,
              'positions',
              null,
              `${row.quantity} units · attributable system quantity; entry basis unavailable`,
              row.version_id,
              'Durable automated fills'
            )
          for (const row of db
            .prepare(
              "SELECT o.*,d.account_id,d.version_id FROM system_orders o JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE v.asset=? AND o.symbol=? AND o.status NOT IN ('filled','canceled','expired','rejected') ORDER BY o.updated_at DESC LIMIT 100"
            )
            .all(asset, symbol) as any[]) {
            const req = parse(row.request_json)
            level(
              row,
              'orders',
              req.limit_price,
              `${row.side} · ${req.type || 'order'} · ${row.status}`,
              row.version_id,
              'System broker request'
            )
            if (req.stop_price)
              level(
                row,
                'protections',
                req.stop_price,
                'Broker stop trigger',
                row.version_id,
                'System broker request',
                'stop'
              )
          }
        }
      })
  } catch {
    unavailable.push(`${scope} ledger unavailable or migration pending`)
  }
  try {
    researchDatabase(false, (db) => {
      previews.push(
        ...db
          .prepare(
            "SELECT p.id,s.name,p.created_at FROM research_previews p JOIN research_snapshots s ON s.id=p.snapshot_id JOIN workspace_jobs j ON j.id=p.id WHERE s.asset=? AND j.status='succeeded' ORDER BY p.created_at DESC LIMIT 30"
          )
          .all(asset)
      )
      if (scope === 'automated')
        for (const r of db
          .prepare(
            'SELECT v.id,v.hypothesis,v.config_json,a.last_decision_at,a.state_json FROM system_versions v LEFT JOIN btc_allocations a ON a.version_id=v.id WHERE v.asset=? ORDER BY v.created_at DESC LIMIT 100'
          )
          .all(asset) as any[]) {
          systems.push({
            id: r.id,
            name: r.hypothesis || r.id.slice(0, 12),
            timeframe: parse(r.config_json).timeframe || '1Day',
            lastDecision: r.last_decision_at,
            state: parse(r.state_json),
          })
        }
      if (query.get('preview')) {
        const r: any = db
          .prepare(
            "SELECT p.result_json,p.id FROM research_previews p JOIN research_snapshots s ON s.id=p.snapshot_id JOIN workspace_jobs j ON j.id=p.id WHERE p.id=? AND s.asset=? AND j.status='succeeded'"
          )
          .get(query.get('preview')!, asset)
        if (!r) throw Error('Preview unavailable')
        const result = parse(r.result_json)
        const row = { id: r.id, account_id: 'research-only', updated_at: result.created_at }
        const inspect = result.inspection?.find((i: any) => i.symbol === symbol)
        const priceKinds = ['close', 'open', 'high', 'low', 'sma', 'ema', 'prior_high', 'prior_low']
        let index = 0
        const visit = (g: any) => {
          for (const condition of g?.conditions || []) {
            if (condition.conditions) visit(condition)
            else
              for (const side of ['left', 'right']) {
                if (
                  priceKinds.includes(condition[side]?.kind) &&
                  Number.isFinite(condition[side + '_value'])
                )
                  level(
                    { ...row, created_at: inspect.completed_bar },
                    'preview',
                    condition[side + '_value'],
                    `PREVIEW ${condition[side].kind}(${condition[side].period || ''}) · ${inspect.completed_bar}`,
                    result.snapshot,
                    'Simulated rule value known at completed bar; not a live system signal',
                    String(index++)
                  )
              }
          }
        }
        if (inspect) {
          visit(inspect.entry)
          visit(inspect.exit)
        }
        for (const [i, f] of (result.continuous?.fills || []).entries())
          if (f.symbol === symbol && previewEvents.length < 200)
            previewEvents.push({
              id: `preview:${r.id}:${i}`,
              at: f.at,
              label: `PREVIEW ${f.side}`,
              side: f.side,
              price: f.price,
              evidence: { ...f, evidence: result.evidence_class, snapshot: result.snapshot },
            })
      }
    })
  } catch {
    unavailable.push('System/preview inspection unavailable or migration pending')
  }
  return {
    asset,
    symbol,
    scope,
    asOf,
    basis: 'raw',
    levels,
    previewEvents,
    previews,
    systems,
    unavailable,
    note: 'Current overlays only; lines do not assert historical order existence. Pending market orders have no fixed price. Missing historical rule evidence is unavailable.',
  }
}
export function activity(query: URLSearchParams) {
  const asset = query.get('asset') === 'bitcoin' ? 'bitcoin' : 'stocks'
  const scope = query.get('scope') || 'manual'
  if (!['manual', 'automated', 'scanner'].includes(scope)) throw Error('Invalid account scope')
  const limit = Math.max(1, Math.min(200, Math.floor(Number(query.get('limit'))) || 50))
  const before = Number(query.get('before')) || Number.MAX_SAFE_INTEGER
  const rows: ActivityRow[] = [],
    unavailable: string[] = []
  const filters: string[] = ['asset=?', 'id<?'],
    args: (string | number)[] = [asset, before]
  for (const key of ['symbol', 'status', 'kind'])
    if (query.get(key)) {
      filters.push(`${key}=?`)
      args.push(query.get(key)!)
    }
  if (query.get('account')) {
    filters.push('account_id=?')
    args.push(query.get('account')!)
  }
  if (scope !== 'manual') {
    filters.push(scope === 'scanner' ? "owner='legacy-scanner'" : "owner!='legacy-scanner'")
    if (query.get('owner')) {
      filters.push('owner=?')
      args.push(query.get('owner')!)
    }
  }
  for (const [key, op] of [
    ['from', '>='],
    ['to', '<='],
  ])
    if (query.get(key)) {
      const date = Date.parse(query.get(key)!)
      if (!Number.isFinite(date)) throw Error('Invalid date filter')
      filters.push(`at${op}?`)
      args.push(scope === 'manual' ? date / 1000 : new Date(date).toISOString())
    }
  const read = (db: DatabaseSync) => {
    const source = scope === 'manual' ? 'activity' : 'workspace_activity'
    for (const r of db
      .prepare(`SELECT * FROM ${source} WHERE ${filters.join(' AND ')} ORDER BY id DESC LIMIT ?`)
      .all(...args, limit + 1) as any[])
      rows.push({
        id: String(r.id),
        asset,
        symbol: r.symbol,
        account: r.account_id,
        owner: r.owner || 'manual',
        entity: r.entity_id || r.instruction_id,
        kind: r.kind,
        status: r.status,
        at: scope === 'manual' ? new Date(r.at * 1000).toISOString() : r.at,
        evidence: parse(r.payload_json || r.payload),
      })
  }
  try {
    if (scope === 'manual') manualRead(read)
    else researchDatabase(false, read)
  } catch {
    unavailable.push('Activity ledger unavailable or migration pending')
  }
  return {
    rows: rows.slice(0, limit),
    next: rows.length > limit ? rows[limit - 1].id : null,
    scope,
    asset,
    unavailable,
    note: 'Prospective state transitions since this release. Older retained fills remain in their original ledgers.',
  }
}
