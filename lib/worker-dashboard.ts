import { easternDayBoundary } from './dashboard-presentation'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { DatabaseSync, type SQLInputValue } from 'node:sqlite'
import type {
  DashboardBacktest,
  DashboardOperations,
  DashboardOverview,
  DashboardPortfolio,
  DashboardScan,
  DashboardSignal,
} from '@/types/dashboard'

type Row = Record<string, unknown>

export class WorkerDatabaseUnavailable extends Error {}

function openWorkerDatabase(): DatabaseSync {
  const configured = process.env.STOCK_WATCH_DATABASE_PATH?.trim()
  if (!configured) {
    throw new WorkerDatabaseUnavailable('Worker database is not configured')
  }
  const path = resolve(configured)
  if (!existsSync(path)) {
    throw new WorkerDatabaseUnavailable('Worker database has not been initialized')
  }
  return new DatabaseSync(path, { readOnly: true })
}

function withDatabase<T>(operation: (database: DatabaseSync) => T): T {
  const database = openWorkerDatabase()
  try {
    database.exec('PRAGMA query_only = ON')
    database.exec('PRAGMA busy_timeout = 3000')
    return operation(database)
  } finally {
    database.close()
  }
}

export function searchUniverse(
  query: string
): { ticker: string; name: string; exchange: string }[] {
  return withDatabase((database) => {
    const term = query
      .trim()
      .slice(0, 80)
      .replace(/[\\%_]/g, '\\$&')
    const rows = database
      .prepare(
        `SELECT symbol, name, exchange FROM instruments
      WHERE active=1 AND (symbol LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')
      ORDER BY CASE WHEN symbol = ? THEN 0 ELSE 1 END, symbol LIMIT 15`
      )
      .all(`${term}%`, `%${term}%`, query.trim().toUpperCase()) as Row[]
    return rows.map((row) => ({
      ticker: String(row.symbol),
      name: textOrNull(row.name) ?? String(row.symbol),
      exchange: textOrNull(row.exchange) ?? '',
    }))
  })
}

export function readDashboardOverview(): DashboardOverview {
  try {
    return withDatabase((database) => {
      const recentScans = readRecentScans(database, 6)
      const latestScan = recentScans[0] ?? null
      const latestScoredScan = recentScans.find((scan) => scan.totalSignals > 0) ?? null
      const topSignals = latestScoredScan
        ? readSignals(database, { scanRunId: latestScoredScan.id, decision: 'qualified', limit: 8 })
        : []
      const portfolio = readPortfolioFromDatabase(database)
      const outcomes = database
        .prepare(
          `SELECT COUNT(*) AS observations,
                  AVG(terminal_positive) AS positive_rate,
                  AVG(beat_spy) AS beat_spy_rate
           FROM signal_outcomes JOIN signals ON signals.id=signal_outcomes.signal_id
           JOIN strategy_versions ON strategy_versions.id=signals.strategy_version_id
           WHERE signals.decision='qualified' AND signal_outcomes.horizon_trading_days=5
             AND signal_outcomes.dataset_version='alpaca-iex-completed-sessions-v2'
             AND strategy_versions.status='paper'`
        )
        .get() as Row
      const failedJobs = database
        .prepare("SELECT COUNT(*) AS count FROM job_runs WHERE status = 'failed'")
        .get() as Row
      const strategy = database
        .prepare(
          `SELECT status FROM strategy_versions
           ORDER BY COALESCE(promoted_at, created_at) DESC LIMIT 1`
        )
        .get() as Row | undefined

      return {
        available: true,
        generatedAt: new Date().toISOString(),
        strategyStatus: textOrNull(strategy?.status),
        latestScan,
        recentScans,
        topSignals,
        metrics: {
          qualifiedSignals: latestScoredScan?.qualifiedSignals ?? 0,
          openLots: portfolio.totals.openLots,
          deployedNotionalUsd: portfolio.totals.deployedNotionalUsd,
          realizedPnlUsd: portfolio.totals.realizedPnlUsd,
          positiveRate: numberOrNull(outcomes.positive_rate),
          beatSpyRate: numberOrNull(outcomes.beat_spy_rate),
          completedOutcomes: numberValue(outcomes.observations),
          failedJobs: numberValue(failedJobs.count),
        },
      }
    })
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) {
      return {
        available: false,
        unavailableReason: error.message,
        generatedAt: new Date().toISOString(),
        strategyStatus: null,
        latestScan: null,
        recentScans: [],
        topSignals: [],
        metrics: {
          qualifiedSignals: 0,
          openLots: 0,
          deployedNotionalUsd: 0,
          realizedPnlUsd: 0,
          positiveRate: null,
          beatSpyRate: null,
          completedOutcomes: 0,
          failedJobs: 0,
        },
      }
    }
    throw error
  }
}

export interface SignalFilters {
  scanRunId?: string
  symbol?: string
  strategyId?: string
  since?: string
  until?: string
  timezone?: string
  offset?: number
  reason?: string
  decision?: string
  horizon?: number
  minimumScore?: number
  limit?: number
}

export function readDashboardSignals(filters: SignalFilters = {}): DashboardSignal[] {
  return withDatabase((database) => readSignals(database, filters))
}

export function readSignalSummary(filters: SignalFilters = {}) {
  return withDatabase((database) => {
    const { where, values } = signalWhere(filters)
    const counts = database
      .prepare(
        `SELECT COUNT(*) AS total, COUNT(DISTINCT instruments.symbol) AS companies
      FROM signals JOIN instruments ON instruments.id=signals.instrument_id ${where}`
      )
      .get(...values) as Row
    const strategies = database
      .prepare('SELECT DISTINCT strategy_version_id AS id FROM signals ORDER BY id')
      .all() as Row[]
    const reasons = database
      .prepare(
        'SELECT DISTINCT value AS reason FROM signals, json_each(signals.reasons_json) ORDER BY reason'
      )
      .all() as Row[]
    return {
      total: Number(counts.total),
      companies: Number(counts.companies),
      strategies: strategies.map((row) => String(row.id)),
      reasons: reasons.map((row) => String(row.reason)),
      generatedAt: new Date().toISOString(),
      scanRunId: filters.scanRunId ?? null,
    }
  })
}

export function readDashboardPortfolio(): DashboardPortfolio {
  return withDatabase(readPortfolioFromDatabase)
}

export function readDashboardBacktests(limit = 50): DashboardBacktest[] {
  return withDatabase((database) => {
    const rows = database
      .prepare(
        `SELECT runs.id, strategy.name AS strategy_name, runs.status,
                runs.dataset_version, runs.dataset_sha256,
                runs.feature_set_version,
                runs.survivorship_biased, runs.round_trip_cost_bps,
                runs.created_at, runs.completed_at, runs.metrics_json,
                COUNT(DISTINCT trades.id) AS trade_count,
                COUNT(DISTINCT rejections.id) AS rejection_count,
                COUNT(DISTINCT splits.id) AS split_count
         FROM backtest_runs AS runs
         JOIN strategy_versions AS strategy ON strategy.id = runs.strategy_version_id
         LEFT JOIN backtest_trades AS trades ON trades.backtest_run_id = runs.id
         LEFT JOIN backtest_rejections AS rejections
           ON rejections.backtest_run_id = runs.id
         LEFT JOIN backtest_splits AS splits ON splits.backtest_run_id = runs.id
         GROUP BY runs.id
         ORDER BY runs.created_at DESC
         LIMIT ?`
      )
      .all(clampLimit(limit)) as Row[]
    return rows.map((row) => ({
      id: String(row.id),
      strategyName: String(row.strategy_name),
      status: String(row.status),
      datasetVersion: String(row.dataset_version),
      datasetSha256: String(row.dataset_sha256),
      featureSetVersion: String(row.feature_set_version),
      survivorshipBiased: Boolean(row.survivorship_biased),
      costBps: numberValue(row.round_trip_cost_bps),
      createdAt: String(row.created_at),
      completedAt: textOrNull(row.completed_at),
      metrics: jsonObject(row.metrics_json),
      tradeCount: numberValue(row.trade_count),
      rejectionCount: numberValue(row.rejection_count),
      splitCount: numberValue(row.split_count),
    }))
  })
}

export function readDashboardOperations(limit = 50): DashboardOperations {
  return withDatabase((database) => {
    const safeLimit = clampLimit(limit)
    const runs = database
      .prepare(
        `SELECT id, command, status, started_at, completed_at, heartbeat_at,
                progress_current, progress_total, message, context_json,
                result_json, error_type, error_message, exception_chain_json,
                traceback, host, process_id,
                MAX(0, (julianday(COALESCE(completed_at, CURRENT_TIMESTAMP)) -
                    julianday(started_at)) * 86400.0) AS duration_seconds
         FROM operation_runs
         ORDER BY started_at DESC
         LIMIT ?`
      )
      .all(safeLimit) as Row[]
    const jobs = database
      .prepare(
        `SELECT id, job_type, status, scheduled_for, attempt, error
         FROM job_runs ORDER BY scheduled_for DESC LIMIT ?`
      )
      .all(safeLimit) as Row[]
    const ingestions = database
      .prepare(
        `SELECT id, dataset, provider, status, completed_at, row_count, error
         FROM data_ingestions ORDER BY started_at DESC LIMIT ?`
      )
      .all(safeLimit) as Row[]
    const reconciliation = database
      .prepare(
        `SELECT reconciliations.captured_at, reconciliations.status,
                reconciliations.expected_positions_json,
                reconciliations.actual_positions_json,
                reconciliations.discrepancies_json,
                reconciliations.corporate_actions_json,
                accounts.status AS account_status, accounts.cash, accounts.equity
         FROM broker_reconciliations AS reconciliations
         JOIN broker_account_snapshots AS accounts
           ON accounts.id = reconciliations.account_snapshot_id
         ORDER BY reconciliations.captured_at DESC, reconciliations.id DESC
         LIMIT 1`
      )
      .get() as Row | undefined
    return {
      brokerReconciliation: reconciliation
        ? {
            capturedAt: String(reconciliation.captured_at),
            status: String(reconciliation.status),
            accountStatus: String(reconciliation.account_status),
            cashUsd: numberValue(reconciliation.cash),
            equityUsd: numberValue(reconciliation.equity),
            expectedPositions: jsonObject(reconciliation.expected_positions_json),
            actualPositions: jsonObject(reconciliation.actual_positions_json),
            discrepancies: jsonObjectArray(reconciliation.discrepancies_json),
            corporateActions: jsonObjectArray(reconciliation.corporate_actions_json),
          }
        : null,
      runs: runs.map((row) => ({
        id: String(row.id),
        command: String(row.command),
        status: String(row.status),
        startedAt: String(row.started_at),
        completedAt: textOrNull(row.completed_at),
        heartbeatAt: String(row.heartbeat_at),
        durationSeconds: numberValue(row.duration_seconds),
        progressCurrent: numberOrNull(row.progress_current),
        progressTotal: numberOrNull(row.progress_total),
        message: textOrNull(row.message),
        context: jsonObject(row.context_json),
        result: jsonObject(row.result_json),
        errorType: textOrNull(row.error_type),
        errorMessage: textOrNull(row.error_message),
        exceptionChain: jsonObjectArray(row.exception_chain_json),
        traceback: textOrNull(row.traceback),
        host: String(row.host),
        processId: numberValue(row.process_id),
      })),
      jobs: jobs.map((row) => ({
        id: String(row.id),
        type: String(row.job_type),
        status: String(row.status),
        scheduledFor: String(row.scheduled_for),
        attempt: numberValue(row.attempt),
        error: textOrNull(row.error),
      })),
      ingestions: ingestions.map((row) => ({
        id: numberValue(row.id),
        dataset: String(row.dataset),
        provider: String(row.provider),
        status: String(row.status),
        completedAt: textOrNull(row.completed_at),
        rowCount: numberValue(row.row_count),
        error: textOrNull(row.error),
      })),
    }
  })
}

function readRecentScans(database: DatabaseSync, limit: number): DashboardScan[] {
  const rows = database
    .prepare(
      `SELECT scans.id, scans.scan_type, scans.scheduled_for, scans.status,
              scans.error, strategy.name AS strategy_name,
              strategy.status AS strategy_status,
              COUNT(signals.id) AS total_signals,
              SUM(CASE WHEN signals.decision = 'qualified' THEN 1 ELSE 0 END)
                  AS qualified_signals
       FROM scan_runs AS scans
       JOIN strategy_versions AS strategy ON strategy.id = scans.strategy_version_id
       LEFT JOIN signals ON signals.scan_run_id = scans.id
       GROUP BY scans.id
       ORDER BY scans.scheduled_for DESC
       LIMIT ?`
    )
    .all(clampLimit(limit)) as Row[]
  return rows.map((row) => ({
    id: String(row.id),
    type: String(row.scan_type),
    scheduledFor: String(row.scheduled_for),
    status: String(row.status),
    strategyName: String(row.strategy_name),
    strategyStatus: String(row.strategy_status),
    qualifiedSignals: numberValue(row.qualified_signals),
    totalSignals: numberValue(row.total_signals),
    error: textOrNull(row.error),
  }))
}

function signalWhere(filters: SignalFilters) {
  const clauses: string[] = []
  const values: SQLInputValue[] = []
  if (filters.scanRunId) {
    clauses.push('signals.scan_run_id = ?')
    values.push(filters.scanRunId)
  }
  if (filters.decision) {
    clauses.push('signals.decision = ?')
    values.push(filters.decision)
  }
  if (filters.horizon) {
    clauses.push('signals.horizon_trading_days = ?')
    values.push(filters.horizon)
  }
  if (filters.minimumScore !== undefined) {
    clauses.push('signals.opportunity_score >= ?')
    values.push(filters.minimumScore)
  }
  if (filters.symbol) {
    clauses.push('instruments.symbol = ?')
    values.push(filters.symbol.trim().toUpperCase())
  }
  if (filters.strategyId) {
    clauses.push('signals.strategy_version_id = ?')
    values.push(filters.strategyId)
  }
  if (filters.timezone === 'America/New_York') {
    if (filters.since) {
      clauses.push('julianday(signals.as_of) >= julianday(?)')
      values.push(easternDayBoundary(filters.since))
    }
    if (filters.until) {
      clauses.push('julianday(signals.as_of) < julianday(?)')
      values.push(easternDayBoundary(filters.until, true))
    }
  } else {
    if (filters.since && /^\d{4}-\d{2}-\d{2}$/.test(filters.since)) {
      clauses.push('date(signals.as_of) >= ?')
      values.push(filters.since)
    }
    if (filters.until && /^\d{4}-\d{2}-\d{2}$/.test(filters.until)) {
      clauses.push('date(signals.as_of) <= ?')
      values.push(filters.until)
    }
  }
  if (filters.reason) {
    clauses.push('EXISTS (SELECT 1 FROM json_each(signals.reasons_json) WHERE value = ?)')
    values.push(filters.reason)
  }
  const where = clauses.length ? `WHERE ${clauses.join(' AND ')}` : ''
  return { where, values }
}

function readSignals(database: DatabaseSync, filters: SignalFilters): DashboardSignal[] {
  const { where, values } = signalWhere(filters)
  values.push(
    clampLimit(filters.limit ?? 100),
    Math.max(0, Math.min(1000000, Math.floor(filters.offset ?? 0)))
  )
  const rows = database
    .prepare(
      `SELECT signals.id, instruments.symbol, instruments.name,
              signals.horizon_trading_days, signals.as_of,
              signals.opportunity_score, signals.data_completeness,
              signals.risk_level, signals.decision, signals.explanation,
              signals.reasons_json, signals.strategy_version_id, signals.scan_run_id,
              evaluations.state AS evaluation_state, evaluations.reason AS evaluation_reason,
              evaluations.checked_at AS evaluation_checked_at, outcomes.dataset_version AS outcome_version,
              (SELECT timestamp FROM market_bars WHERE instrument_id=signals.instrument_id
               AND timeframe='1Day' AND adjustment='all' AND provider='alpaca'
               ORDER BY timestamp DESC LIMIT 1) AS price_as_of,
              orders.status AS order_status, orders.error AS order_error,
              orders.notional_usd, lots.status AS lot_status,
              outcomes.net_return, outcomes.excess_return, outcomes.beat_spy,
              (SELECT bars.close FROM market_bars AS bars
               WHERE bars.instrument_id = signals.instrument_id
                 AND bars.timeframe = '1Day' AND bars.adjustment = 'all'
                 AND bars.provider = 'alpaca'
               ORDER BY bars.timestamp DESC LIMIT 1) AS current_price
       FROM signals
       JOIN instruments ON instruments.id = signals.instrument_id
       LEFT JOIN paper_orders AS orders ON orders.signal_id = signals.id
       LEFT JOIN paper_trade_lots AS lots ON lots.signal_id = signals.id
       LEFT JOIN signal_outcomes AS outcomes
          ON outcomes.signal_id = signals.id
         AND outcomes.horizon_trading_days = signals.horizon_trading_days
       LEFT JOIN signal_evaluations AS evaluations ON evaluations.signal_id=signals.id
       ${where}
       ORDER BY signals.as_of DESC, signals.opportunity_score DESC,
                signals.horizon_trading_days, signals.id
       LIMIT ? OFFSET ?`
    )
    .all(...values) as Row[]
  const signalIds = rows.map((row) => String(row.id))
  const pillars = new Map<string, DashboardSignal['pillars']>()
  if (signalIds.length) {
    const placeholders = signalIds.map(() => '?').join(',')
    const componentRows = database
      .prepare(
        `SELECT signal_id, name, normalized_score, weight,
                weighted_points, available
         FROM signal_components
         WHERE signal_id IN (${placeholders})
         ORDER BY signal_id, weighted_points DESC`
      )
      .all(...signalIds) as Row[]
    for (const row of componentRows) {
      const id = String(row.signal_id)
      const values = pillars.get(id) ?? []
      values.push({
        name: String(row.name),
        score: numberOrNull(row.normalized_score),
        weight: numberValue(row.weight),
        weightedPoints: numberValue(row.weighted_points),
        available: Boolean(row.available),
      })
      pillars.set(id, values)
    }
  }
  const events = new Map<string, DashboardSignal['events']>()
  if (signalIds.length) {
    const placeholders = signalIds.map(() => '?').join(',')
    const records = database
      .prepare(
        `WITH selected AS (SELECT id FROM signals WHERE id IN (${placeholders})),
      entities AS (
        SELECT id AS signal_id, 'signal' AS entity_type, id AS entity_id FROM selected
        UNION ALL SELECT orders.signal_id, 'paper_order', orders.id FROM paper_orders AS orders JOIN selected ON selected.id=orders.signal_id
        UNION ALL SELECT lots.signal_id, 'paper_trade_lot', lots.id FROM paper_trade_lots AS lots JOIN selected ON selected.id=lots.signal_id
        UNION ALL SELECT lots.signal_id, 'paper_exit_order', exits.id FROM paper_exit_orders AS exits JOIN paper_trade_lots AS lots ON lots.id=exits.lot_id JOIN selected ON selected.id=lots.signal_id
      ) SELECT entities.signal_id, events.occurred_at, events.event_type, events.payload_json
      FROM entities JOIN audit_events AS events ON events.entity_type=entities.entity_type AND events.entity_id=entities.entity_id
      ORDER BY events.occurred_at, events.id`
      )
      .all(...signalIds) as Row[]
    for (const event of records) {
      const id = String(event.signal_id)
      const list = events.get(id) ?? []
      const payload = JSON.parse(String(event.payload_json))
      list.push({
        at: String(event.occurred_at),
        type: String(event.event_type),
        detail: JSON.stringify(payload),
      })
      events.set(id, list)
    }
  }
  const reviews = new Map<string, DashboardSignal['qualityReview']>()
  if (
    signalIds.length &&
    database.prepare("SELECT 1 FROM sqlite_master WHERE name='assessment_reviews'").get()
  ) {
    const records = database
      .prepare(
        `SELECT signal_id,quality_json FROM assessment_reviews WHERE signal_id IN (${signalIds.map(() => '?').join(',')})`
      )
      .all(...signalIds) as Row[]
    for (const row of records) {
      const review = jsonObject(row.quality_json)
      reviews.set(String(row.signal_id), {
        coverage: Number(review.metric_coverage ?? 0),
        blockers: Array.isArray(review.blockers) ? review.blockers.map(String) : [],
        warnings: Array.isArray(review.warnings) ? review.warnings.map(String) : [],
        anomalies: Array.isArray(review.anomalies) ? review.anomalies.length : 0,
      })
    }
  }
  return rows.map((row) => ({
    qualityReview: reviews.get(String(row.id)),
    id: String(row.id),
    symbol: String(row.symbol),
    companyName: textOrNull(row.name),
    horizonTradingDays: numberValue(row.horizon_trading_days),
    asOf: String(row.as_of),
    score: numberValue(row.opportunity_score),
    completeness: numberValue(row.data_completeness),
    risk: String(row.risk_level) as DashboardSignal['risk'],
    decision: String(row.decision),
    explanation: String(row.explanation),
    reasons: jsonStrings(row.reasons_json),
    pillars: pillars.get(String(row.id)) ?? [],
    orderStatus: textOrNull(row.order_status),
    orderError: textOrNull(row.order_error),
    notionalUsd: numberOrNull(row.notional_usd),
    lotStatus: textOrNull(row.lot_status),
    netReturn: numberOrNull(row.net_return),
    excessReturn: numberOrNull(row.excess_return),
    beatSpy: row.beat_spy === null || row.beat_spy === undefined ? null : Boolean(row.beat_spy),
    currentPrice: numberOrNull(row.current_price),
    priceAsOf: textOrNull(row.price_as_of),
    strategyId: String(row.strategy_version_id),
    scanRunId: String(row.scan_run_id),
    evaluationState: textOrNull(row.evaluation_state),
    evaluationReason: textOrNull(row.evaluation_reason),
    evaluationCheckedAt: textOrNull(row.evaluation_checked_at),
    outcomeVersion: textOrNull(row.outcome_version),
    events: events.get(String(row.id)) ?? [],
  }))
}

function readPortfolioFromDatabase(database: DatabaseSync): DashboardPortfolio {
  const rows = database
    .prepare(
      `SELECT lots.id, instruments.symbol, lots.horizon_trading_days,
              lots.status, signals.opportunity_score,
              lots.entry_notional_usd, lots.entry_price,
              lots.entry_quantity, lots.opened_at, lots.target_exit_at,
              lots.closed_at, lots.exit_price, lots.exit_quantity,
              lots.realized_return,
              orders.status AS order_status,
              exits.status AS exit_order_status, exits.error AS exit_order_error
       FROM paper_trade_lots AS lots
       JOIN instruments ON instruments.id = lots.instrument_id
       JOIN signals ON signals.id = lots.signal_id
       JOIN paper_orders AS orders ON orders.id = lots.entry_order_id
       LEFT JOIN paper_exit_orders AS exits ON exits.lot_id = lots.id
       ORDER BY COALESCE(lots.opened_at, lots.created_at) DESC`
    )
    .all() as Row[]
  const lots = rows.map((row) => ({
    id: String(row.id),
    symbol: String(row.symbol),
    horizonTradingDays: numberValue(row.horizon_trading_days),
    status: String(row.status),
    score: numberValue(row.opportunity_score),
    entryNotionalUsd: numberValue(row.entry_notional_usd),
    entryPrice: numberOrNull(row.entry_price),
    entryQuantity: numberOrNull(row.entry_quantity),
    openedAt: textOrNull(row.opened_at),
    targetExitAt: textOrNull(row.target_exit_at),
    closedAt: textOrNull(row.closed_at),
    exitPrice: numberOrNull(row.exit_price),
    exitQuantity: numberOrNull(row.exit_quantity),
    realizedReturn: numberOrNull(row.realized_return),
    orderStatus: String(row.order_status),
    exitOrderStatus: textOrNull(row.exit_order_status),
    exitOrderError: textOrNull(row.exit_order_error),
  }))
  const openLots = lots.filter((lot) => ['pending', 'open', 'closing'].includes(lot.status))
  const historyRows = database
    .prepare(
      `SELECT observed_at, equity, spy_value, contributed_capital,
              realized_pnl, unrealized_pnl
       FROM (SELECT * FROM portfolio_snapshots ORDER BY observed_at DESC LIMIT 1000) ORDER BY observed_at ASC`
    )
    .all() as Row[]
  const history = historyRows.map((row) => ({
    observedAt: String(row.observed_at),
    equity: numberValue(row.equity),
    contributedCapital: numberValue(row.contributed_capital),
    spyValue: numberOrNull(row.spy_value),
    realizedPnl: numberValue(row.realized_pnl),
    unrealizedPnl: numberValue(row.unrealized_pnl),
  }))
  const latestRow = database
    .prepare('SELECT observed_at FROM portfolio_snapshots ORDER BY observed_at DESC LIMIT 1')
    .get() as Row | undefined
  const latest = history.at(-1)
  const contributedFromLots = lots.reduce(
    (sum, lot) => sum + (lot.entryPrice ?? 0) * (lot.entryQuantity ?? 0),
    0
  )
  const realizedFromLots = lots.reduce(
    (sum, lot) => sum + ((lot.exitPrice ?? 0) - (lot.entryPrice ?? 0)) * (lot.exitQuantity ?? 0),
    0
  )
  const contributedCapital = latest?.contributedCapital ?? contributedFromLots
  const equity = latest?.equity ?? contributedFromLots + realizedFromLots
  const spyValue = latest?.spyValue ?? null
  const portfolioReturn =
    contributedCapital > 0 ? (equity - contributedCapital) / contributedCapital : null
  const spyReturn =
    contributedCapital > 0 && spyValue !== null
      ? (spyValue - contributedCapital) / contributedCapital
      : null
  return {
    lots,
    snapshotAt: latestRow ? String(latestRow.observed_at) : null,
    performanceAvailable: Boolean(latest),
    generatedAt: new Date().toISOString(),
    totals: {
      lots: lots.length,
      openLots: openLots.filter((lot) => lot.status !== 'pending').length,
      pendingLots: openLots.filter((lot) => lot.status === 'pending').length,
      reservedNotionalUsd: openLots
        .filter((lot) => lot.status === 'pending')
        .reduce((sum, lot) => sum + lot.entryNotionalUsd, 0),
      deployedNotionalUsd: openLots
        .filter((lot) => lot.status !== 'pending')
        .reduce((sum, lot) => sum + (lot.entryPrice ?? 0) * (lot.entryQuantity ?? 0), 0),
      contributedCapitalUsd: contributedCapital,
      equityUsd: equity,
      realizedPnlUsd: latest?.realizedPnl ?? realizedFromLots,
      unrealizedPnlUsd: latest?.unrealizedPnl ?? 0,
      spyValueUsd: spyValue,
      excessVsSpyUsd: spyValue === null ? null : equity - spyValue,
      portfolioReturn,
      spyReturn,
      excessReturn:
        portfolioReturn === null || spyReturn === null ? null : portfolioReturn - spyReturn,
    },
    history,
  }
}

function numberValue(value: unknown): number {
  return value === null || value === undefined ? 0 : Number(value)
}

function numberOrNull(value: unknown): number | null {
  return value === null || value === undefined ? null : Number(value)
}

function textOrNull(value: unknown): string | null {
  return value === null || value === undefined ? null : String(value)
}

function jsonStrings(value: unknown): string[] {
  try {
    const parsed = JSON.parse(String(value))
    return Array.isArray(parsed) ? parsed.map(String) : []
  } catch {
    return []
  }
}

function jsonObject(value: unknown): Record<string, unknown> {
  try {
    const parsed = JSON.parse(String(value))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function jsonObjectArray(value: unknown): Array<Record<string, unknown>> {
  try {
    const parsed = JSON.parse(String(value))
    return Array.isArray(parsed)
      ? parsed.filter(
          (item): item is Record<string, unknown> =>
            Boolean(item) && typeof item === 'object' && !Array.isArray(item)
        )
      : []
  } catch {
    return []
  }
}

function clampLimit(value: number): number {
  if (!Number.isFinite(value)) return 50
  return Math.max(1, Math.min(500, Math.trunc(value)))
}

export function readResearchSummary() {
  return withDatabase((database) => {
    const latest = database
      .prepare(
        "SELECT id FROM scan_runs WHERE status='succeeded' ORDER BY scheduled_for DESC LIMIT 1"
      )
      .get() as Row | undefined
    const counts = latest
      ? (database
          .prepare(
            `SELECT COUNT(*) AS observations, COUNT(DISTINCT instrument_id) AS companies,
      COUNT(DISTINCT CASE WHEN decision='qualified' THEN instrument_id END) AS qualified_companies
      FROM signals WHERE scan_run_id=?`
          )
          .get(String(latest.id)) as Row)
      : undefined
    const reasons = latest
      ? (database
          .prepare(
            `SELECT reasons.value AS reason, COUNT(*) AS observations,
      COUNT(DISTINCT signals.instrument_id) AS companies
      FROM signals, json_each(signals.reasons_json) AS reasons WHERE signals.scan_run_id=?
      GROUP BY reasons.value ORDER BY companies DESC LIMIT 8`
          )
          .all(String(latest.id)) as Row[])
      : []
    const horizons = database
      .prepare(
        `SELECT outcomes.horizon_trading_days AS horizon, COUNT(*) AS observations,
      COUNT(DISTINCT signals.instrument_id) AS companies, AVG(outcomes.terminal_positive) AS positive,
      AVG(outcomes.beat_spy) AS beat_spy, AVG(outcomes.net_return) AS net_return
      FROM signal_outcomes AS outcomes JOIN signals ON signals.id=outcomes.signal_id
      JOIN strategy_versions AS strategy ON strategy.id=signals.strategy_version_id
      WHERE signals.decision='qualified' AND outcomes.dataset_version='alpaca-iex-completed-sessions-v2' AND strategy.status='paper'
      GROUP BY outcomes.horizon_trading_days`
      )
      .all() as Row[]
    return {
      scanRunId: latest ? String(latest.id) : null,
      companies: numberValue(counts?.companies),
      observations: numberValue(counts?.observations),
      qualifiedCompanies: numberValue(counts?.qualified_companies),
      reasons,
      horizons,
    }
  })
}

export function readExecutionSnapshot(): import('@/lib/execution-status-model').ExecutionSnapshot {
  return withDatabase((database) => {
    const strategyId = process.env.STOCK_WATCH_STRATEGY_ID?.trim() || null
    const strategy = strategyId
      ? (database
          .prepare('SELECT status, promoted_at, created_at FROM strategy_versions WHERE id=?')
          .get(strategyId) as Row | undefined)
      : undefined
    const scan = (
      row: Row | undefined
    ): import('@/lib/execution-status-model').StatusScan | null =>
      row
        ? {
            id: String(row.id),
            type: String(row.scan_type),
            at: String(row.scheduled_for),
            completedAt: textOrNull(row.completed_at),
            status: String(row.status),
            strategyId: String(row.strategy_version_id),
            error: textOrNull(row.error),
          }
        : null
    const latest = strategyId
      ? (database
          .prepare(
            'SELECT * FROM scan_runs WHERE strategy_version_id=? ORDER BY scheduled_for DESC LIMIT 1'
          )
          .get(strategyId) as Row | undefined)
      : undefined
    const success = database
      .prepare(
        "SELECT * FROM scan_runs WHERE status='succeeded' ORDER BY scheduled_for DESC LIMIT 1"
      )
      .get() as Row | undefined
    const scheduled = strategyId
      ? (database
          .prepare(
            "SELECT * FROM scan_runs WHERE strategy_version_id=? AND status='succeeded' AND scan_type IN ('open','close') ORDER BY scheduled_for DESC LIMIT 1"
          )
          .get(strategyId) as Row | undefined)
      : undefined
    const reconciliation = database
      .prepare(
        'SELECT status,captured_at FROM broker_reconciliations ORDER BY captured_at DESC,id DESC LIMIT 1'
      )
      .get() as Row | undefined
    const ingestions = database
      .prepare(
        `SELECT dataset, MAX(completed_at) AS completed_at FROM data_ingestions
      WHERE status='succeeded' AND dataset IN ('scan_bundle','historical_calendar') GROUP BY dataset`
      )
      .all() as Row[]
    const fundamentals = database
      .prepare(
        "SELECT completed_at FROM operation_runs WHERE command='refresh-fundamentals' AND status='succeeded' ORDER BY completed_at DESC LIMIT 1"
      )
      .get() as Row | undefined
    if (fundamentals)
      ingestions.push({ dataset: 'company_facts', completed_at: fundamentals.completed_at })
    return {
      strategyId,
      strategyStatus: textOrNull(strategy?.status),
      strategySince: textOrNull(strategy?.promoted_at ?? strategy?.created_at),
      credentialsConfigured: Boolean(
        process.env.ALPACA_API_KEY_ID && process.env.ALPACA_API_SECRET_KEY
      ),
      latestScan: scan(latest),
      lastSuccess: scan(success),
      lastScheduledSuccess: scan(scheduled),
      reconciliation: reconciliation
        ? { status: String(reconciliation.status), at: String(reconciliation.captured_at) }
        : null,
      ingestions: ingestions.map((row) => ({
        dataset: String(row.dataset),
        at: textOrNull(row.completed_at),
        status: 'succeeded',
      })),
    }
  })
}

export function readLiquidityDiagnostics() {
  return withDatabase((database) => {
    const latest = database
      .prepare(
        "SELECT id,scheduled_for,strategy_version_id FROM scan_runs WHERE status='succeeded' ORDER BY scheduled_for DESC LIMIT 1"
      )
      .get() as Row | undefined
    if (!latest) return null
    const rows = database
      .prepare(
        `SELECT DISTINCT instruments.symbol, signals.risk_level, signals.decision,
      signals.opportunity_score, signals.reasons_json,
      json_extract(features.features_json,'$.raw.average_dollar_volume_21') AS liquidity,
      json_extract(features.features_json,'$.raw.annualized_volatility_21') AS volatility,
      json_extract(features.features_json,'$.raw.maximum_drawdown_63') AS drawdown
      FROM signals JOIN instruments ON instruments.id=signals.instrument_id
      JOIN feature_snapshots AS features ON features.id=signals.feature_snapshot_id
      WHERE signals.scan_run_id=? ORDER BY instruments.symbol`
      )
      .all(String(latest.id)) as Row[]
    // The current strategy repeats risk inputs across horizons. Group explicitly
    // by company so four horizons cannot inflate this diagnostic.
    const companies = [...new Map(rows.map((row) => [String(row.symbol), row])).values()].map(
      (row) => {
        const liquidity = numberOrNull(row.liquidity),
          volatility = numberOrNull(row.volatility),
          drawdown = numberOrNull(row.drawdown)
        const lowVolume = liquidity !== null && liquidity < 20000000
        const volatile = volatility !== null && volatility > 0.6
        const deepDrawdown = drawdown !== null && drawdown < -0.3
        return {
          symbol: String(row.symbol),
          liquidity,
          volatility,
          drawdown,
          risk: String(row.risk_level),
          score: numberValue(row.opportunity_score),
          decision: String(row.decision),
          reasons: jsonStrings(row.reasons_json),
          lowVolume,
          volatile,
          deepDrawdown,
          liquidityOnly:
            lowVolume && volatility !== null && drawdown !== null && !volatile && !deepDrawdown,
        }
      }
    )
    return {
      scanId: String(latest.id),
      at: String(latest.scheduled_for),
      strategyId: String(latest.strategy_version_id),
      companies: companies.length,
      highRisk: companies.filter((row) => row.risk === 'high').length,
      lowVolume: companies.filter((row) => row.lowVolume).length,
      liquidityOnly: companies.filter((row) => row.liquidityOnly).length,
      volatility: companies.filter((row) => row.volatile).length,
      drawdown: companies.filter((row) => row.deepDrawdown).length,
      missingInputs: companies.filter(
        (row) => row.liquidity === null || row.volatility === null || row.drawdown === null
      ).length,
      riskOnlyRejection: companies.filter(
        (row) =>
          row.liquidityOnly && row.reasons.length === 1 && row.reasons[0] === 'risk_not_allowed'
      ).length,
      examples: companies
        .filter((row) => row.liquidityOnly)
        .sort((a, b) => b.score - a.score)
        .slice(0, 10),
      thresholds: {
        liquidityHigh: 20000000,
        liquidityMedium: 50000000,
        volatilityHigh: 0.6,
        drawdownHigh: -0.3,
      },
    }
  })
}

export function readAssessmentDashboard() {
  return withDatabase((database) => {
    const strategy = database
      .prepare('SELECT id,config_json FROM strategy_versions WHERE id=?')
      .get(process.env.STOCK_WATCH_STRATEGY_ID ?? 'sp500-long-paper-v2') as Row | undefined
    const config = strategy ? JSON.parse(String(strategy.config_json)) : {}
    const sectors = database
      .prepare(
        `SELECT COALESCE(c.sector,'Unknown') AS sector,
      SUM(l.entry_notional_usd) AS committed,
      SUM(CASE WHEN l.status='pending' THEN l.entry_notional_usd ELSE 0 END) AS reserved,
      COUNT(*) AS lots FROM paper_trade_lots l LEFT JOIN instrument_context c ON c.instrument_id=l.instrument_id
      WHERE l.status IN ('pending','open','closing') GROUP BY COALESCE(c.sector,'Unknown') ORDER BY committed DESC`
      )
      .all() as Row[]
    const coverage = database
      .prepare(
        `SELECT COUNT(*) AS total,SUM(c.sector IS NOT NULL) AS classified
      FROM instruments i LEFT JOIN instrument_context c ON c.instrument_id=i.id
      WHERE i.id IN (SELECT instrument_id FROM universe_memberships WHERE snapshot_id=(SELECT id FROM universe_snapshots ORDER BY effective_at DESC,id DESC LIMIT 1))`
      )
      .get() as Row
    const variants = database
      .prepare(
        `SELECT s.strategy_version_id AS strategy,a.variant,a.config_json,s.horizon_trading_days AS horizon,
      COUNT(*) AS observations,COUNT(DISTINCT s.instrument_id) AS companies,
      SUM(a.qualified) AS qualified,
      SUM(CASE WHEN a.qualified=1 AND o.signal_id IS NOT NULL THEN 1 ELSE 0 END) AS matured,
      AVG(CASE WHEN a.qualified=1 THEN o.net_return END) AS net_return,
      AVG(CASE WHEN a.qualified=1 THEN o.excess_return END) AS excess_return,
      AVG(CASE WHEN a.qualified=1 THEN o.beat_spy END) AS beat_spy,
      MIN(s.as_of) AS first_at,MAX(s.as_of) AS last_at
      FROM shadow_assessments a JOIN signals s ON s.id=a.signal_id
      LEFT JOIN signal_outcomes o ON o.signal_id=s.id AND o.horizon_trading_days=s.horizon_trading_days
        AND o.dataset_version='alpaca-iex-completed-sessions-v2'
      GROUP BY s.strategy_version_id,a.variant,a.config_json,s.horizon_trading_days
      ORDER BY last_at DESC,strategy,horizon,a.variant LIMIT 120`
      )
      .all() as Row[]
    const rejected = database
      .prepare(
        `SELECT s.strategy_version_id AS strategy,s.horizon_trading_days AS horizon,
      CASE WHEN s.opportunity_score>=json_extract(v.config_json,'$.qualification.minimum_score')-5
        THEN 'Near threshold (within 5 points or higher)' ELSE 'Below threshold by more than 5 points' END AS cohort,
      COUNT(*) AS observations,COUNT(o.signal_id) AS matured,AVG(o.net_return) AS net_return,AVG(o.excess_return) AS excess_return
      FROM signals s JOIN strategy_versions v ON v.id=s.strategy_version_id
      JOIN assessment_reviews r ON r.signal_id=s.id
      LEFT JOIN signal_outcomes o ON o.signal_id=s.id AND o.horizon_trading_days=s.horizon_trading_days
        AND o.dataset_version='alpaca-iex-completed-sessions-v2'
      WHERE s.decision='rejected' GROUP BY s.strategy_version_id,s.horizon_trading_days,cohort ORDER BY strategy,horizon`
      )
      .all() as Row[]
    const entries = database
      .prepare(
        `SELECT o.id,i.symbol,s.horizon_trading_days AS horizon,o.notional_usd,o.status,
      e.checked_at,e.decision,e.reason,e.details_json,d.next_check_at,d.expires_at
      FROM paper_orders o JOIN signals s ON s.id=o.signal_id JOIN instruments i ON i.id=s.instrument_id
      LEFT JOIN entry_checks e ON e.id=(SELECT id FROM entry_checks WHERE order_id=o.id ORDER BY checked_at DESC,id DESC LIMIT 1)
      LEFT JOIN deferred_entries d ON d.order_id=o.id
      WHERE e.id IS NOT NULL OR d.order_id IS NOT NULL
      ORDER BY CASE WHEN o.status='pending' THEN 0 ELSE 1 END,e.checked_at DESC LIMIT 40`
      )
      .all() as Row[]
    return {
      strategy: strategy ? String(strategy.id) : null,
      policyEnabled: config.entry_policy?.enabled === true,
      maximum: Number(config.portfolio?.maximum_notional_usd ?? 300),
      sectorMaximum: Number(config.portfolio?.maximum_sector_notional_usd ?? 60),
      committed: sectors.reduce((sum, row) => sum + Number(row.committed), 0),
      reserved: sectors.reduce((sum, row) => sum + Number(row.reserved), 0),
      sectors,
      coverage,
      variants: variants.map((row) => ({ ...row })),
      rejected,
      entries,
    }
  })
}
