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

export function readDashboardOverview(): DashboardOverview {
  try {
    return withDatabase(database => {
      const recentScans = readRecentScans(database, 6)
      const latestScan = recentScans[0] ?? null
      const latestScoredScan = recentScans.find(scan => scan.totalSignals > 0) ?? null
      const topSignals = latestScoredScan
        ? readSignals(database, { scanRunId: latestScoredScan.id, decision: 'qualified', limit: 8 })
        : []
      const portfolio = readPortfolioFromDatabase(database)
      const outcomes = database
        .prepare(
          `SELECT COUNT(*) AS observations,
                  AVG(terminal_positive) AS positive_rate,
                  AVG(beat_spy) AS beat_spy_rate
           FROM signal_outcomes`
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

export function readDashboardSignals(filters: {
  decision?: string
  horizon?: number
  minimumScore?: number
  limit?: number
} = {}): DashboardSignal[] {
  return withDatabase(database => readSignals(database, filters))
}

export function readDashboardPortfolio(): DashboardPortfolio {
  return withDatabase(readPortfolioFromDatabase)
}

export function readDashboardBacktests(limit = 50): DashboardBacktest[] {
  return withDatabase(database => {
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
    return rows.map(row => ({
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
  return withDatabase(database => {
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
      runs: runs.map(row => ({
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
      jobs: jobs.map(row => ({
        id: String(row.id),
        type: String(row.job_type),
        status: String(row.status),
        scheduledFor: String(row.scheduled_for),
        attempt: numberValue(row.attempt),
        error: textOrNull(row.error),
      })),
      ingestions: ingestions.map(row => ({
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
  return rows.map(row => ({
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

function readSignals(
  database: DatabaseSync,
  filters: {
    scanRunId?: string
    decision?: string
    horizon?: number
    minimumScore?: number
    limit?: number
  }
): DashboardSignal[] {
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
  const where = clauses.length ? `WHERE ${clauses.join(' AND ')}` : ''
  values.push(clampLimit(filters.limit ?? 100))
  const rows = database
    .prepare(
      `SELECT signals.id, instruments.symbol, instruments.name,
              signals.horizon_trading_days, signals.as_of,
              signals.opportunity_score, signals.data_completeness,
              signals.risk_level, signals.decision, signals.explanation,
              signals.reasons_json, orders.status AS order_status,
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
       ${where}
       ORDER BY signals.as_of DESC, signals.opportunity_score DESC,
                signals.horizon_trading_days
       LIMIT ?`
    )
    .all(...values) as Row[]
  const signalIds = rows.map(row => String(row.id))
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
  return rows.map(row => ({
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
    notionalUsd: numberOrNull(row.notional_usd),
    lotStatus: textOrNull(row.lot_status),
    netReturn: numberOrNull(row.net_return),
    excessReturn: numberOrNull(row.excess_return),
    beatSpy: row.beat_spy === null || row.beat_spy === undefined ? null : Boolean(row.beat_spy),
    currentPrice: numberOrNull(row.current_price),
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
              exits.status AS exit_order_status
       FROM paper_trade_lots AS lots
       JOIN instruments ON instruments.id = lots.instrument_id
       JOIN signals ON signals.id = lots.signal_id
       JOIN paper_orders AS orders ON orders.id = lots.entry_order_id
       LEFT JOIN paper_exit_orders AS exits ON exits.lot_id = lots.id
       ORDER BY COALESCE(lots.opened_at, lots.created_at) DESC`
    )
    .all() as Row[]
  const lots = rows.map(row => ({
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
  }))
  const openLots = lots.filter(lot => ['pending', 'open', 'closing'].includes(lot.status))
  const historyRows = database
    .prepare(
      `SELECT observed_at, equity, spy_value, contributed_capital,
              realized_pnl, unrealized_pnl
       FROM portfolio_snapshots ORDER BY observed_at ASC LIMIT 1000`
    )
    .all() as Row[]
  const history = historyRows.map(row => ({
    observedAt: String(row.observed_at),
    equity: numberValue(row.equity),
    contributedCapital: numberValue(row.contributed_capital),
    spyValue: numberOrNull(row.spy_value),
    realizedPnl: numberValue(row.realized_pnl),
    unrealizedPnl: numberValue(row.unrealized_pnl),
  }))
  const latest = history.at(-1)
  const contributedFromLots = lots.reduce(
    (sum, lot) => sum + (lot.entryPrice ?? 0) * (lot.entryQuantity ?? 0),
    0
  )
  const realizedFromLots = lots.reduce(
    (sum, lot) =>
      sum +
      ((lot.exitPrice ?? 0) - (lot.entryPrice ?? 0)) * (lot.exitQuantity ?? 0),
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
    totals: {
      lots: lots.length,
      openLots: openLots.length,
      deployedNotionalUsd: openLots.reduce(
        (sum, lot) => sum + ((lot.entryPrice ?? 0) * (lot.entryQuantity ?? 0) || lot.entryNotionalUsd),
        0
      ),
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
