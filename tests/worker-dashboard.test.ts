import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import {
  readExecutionSnapshot,
  readLiquidityDiagnostics,
  readDashboardBacktests,
  readDashboardOverview,
  readDashboardOperations,
  readDashboardPortfolio,
  readDashboardSignals,
  readSignalSummary,
} from '@/lib/worker-dashboard'

describe('worker dashboard database', () => {
  let directory: string
  let databasePath: string
  const originalPath = process.env.STOCK_WATCH_DATABASE_PATH

  beforeEach(() => {
    directory = mkdtempSync(join(tmpdir(), 'stock-watch-dashboard-'))
    databasePath = join(directory, 'worker.db')
  })

  afterEach(() => {
    if (originalPath === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
    else process.env.STOCK_WATCH_DATABASE_PATH = originalPath
    rmSync(directory, { recursive: true, force: true })
  })

  test('returns an intentional unavailable state when not configured', () => {
    delete process.env.STOCK_WATCH_DATABASE_PATH

    const overview = readDashboardOverview()

    expect(overview.available).toBe(false)
    expect(overview.unavailableReason).toMatch(/not configured/)
  })

  test('execution status uses the configured strategy instead of the newest unrelated strategy', () => {
    createFixtureDatabase(databasePath)
    process.env.STOCK_WATCH_DATABASE_PATH = databasePath
    const previous = process.env.STOCK_WATCH_STRATEGY_ID
    process.env.STOCK_WATCH_STRATEGY_ID = 'strategy-v0'
    const db = new DatabaseSync(databasePath)
    db.exec(
      "INSERT INTO strategy_versions VALUES ('other', 'Other', 'paper', '2026-09-17T00:00:00Z', '2026-09-17T00:00:00Z')"
    )
    try {
      expect(readExecutionSnapshot()).toMatchObject({
        strategyId: 'strategy-v0',
        strategyStatus: 'development',
        lastScheduledSuccess: { id: 'scan-1' },
      })
      process.env.STOCK_WATCH_STRATEGY_ID = 'missing'
      expect(readExecutionSnapshot()).toMatchObject({
        strategyStatus: null,
        lastScheduledSuccess: null,
      })
    } finally {
      db.close()
      if (previous === undefined) delete process.env.STOCK_WATCH_STRATEGY_ID
      else process.env.STOCK_WATCH_STRATEGY_ID = previous
    }
  })

  test('liquidity diagnostics count companies once and separate overlapping risk triggers', () => {
    createFixtureDatabase(databasePath)
    process.env.STOCK_WATCH_DATABASE_PATH = databasePath
    const db = new DatabaseSync(databasePath)
    db.exec(`CREATE TABLE feature_snapshots (id INTEGER, features_json TEXT);
      ALTER TABLE signals ADD COLUMN feature_snapshot_id INTEGER;
      UPDATE signals SET feature_snapshot_id=1, risk_level='high', decision='rejected', reasons_json='["risk_not_allowed"]';
      INSERT INTO feature_snapshots VALUES (1, '{"raw":{"average_dollar_volume_21":10000000,"annualized_volatility_21":0.3,"maximum_drawdown_63":-0.1}}');
      INSERT INTO signals SELECT 'signal-2', scan_run_id, instrument_id, 5, as_of, opportunity_score, data_completeness, risk_level, decision, explanation, reasons_json, strategy_version_id, feature_snapshot_id FROM signals WHERE id='signal-1';`)
    expect(readLiquidityDiagnostics()).toMatchObject({
      companies: 1,
      highRisk: 1,
      lowVolume: 1,
      liquidityOnly: 1,
      riskOnlyRejection: 1,
    })
    db.exec(
      `UPDATE feature_snapshots SET features_json='{"raw":{"average_dollar_volume_21":10000000,"annualized_volatility_21":0.7,"maximum_drawdown_63":-0.1}}'`
    )
    expect(readLiquidityDiagnostics()).toMatchObject({
      companies: 1,
      lowVolume: 1,
      volatility: 1,
      liquidityOnly: 0,
      riskOnlyRejection: 0,
    })
    db.exec(
      `UPDATE feature_snapshots SET features_json='{"raw":{"average_dollar_volume_21":20000000,"annualized_volatility_21":null,"maximum_drawdown_63":-0.1}}'`
    )
    expect(readLiquidityDiagnostics()).toMatchObject({
      lowVolume: 0,
      missingInputs: 1,
      liquidityOnly: 0,
    })
    db.close()
  })

  test('reads ranked signals and factor contributions from SQLite', () => {
    createFixtureDatabase(databasePath)
    process.env.STOCK_WATCH_DATABASE_PATH = databasePath

    const overview = readDashboardOverview()
    const signals = readDashboardSignals({ decision: 'qualified' })
    const portfolio = readDashboardPortfolio()

    expect(overview.available).toBe(true)
    expect(overview.metrics.qualifiedSignals).toBe(1)
    expect(overview.topSignals).toHaveLength(1)
    expect(signals[0]).toMatchObject({
      symbol: 'AAPL',
      score: 86,
      currentPrice: 210,
      decision: 'qualified',
    })
    expect(signals[0].events).toEqual([expect.objectContaining({ type: 'paper_order_reconciled' })])
    expect(readDashboardSignals({ symbol: 'MSFT' })).toHaveLength(0)
    expect(readDashboardSignals({ symbol: 'aapl', offset: 1 })).toHaveLength(0)
    expect(
      readDashboardSignals({ symbol: 'aapl', since: '2026-08-20', until: '2026-08-20' })
    ).toHaveLength(1)
    expect(readDashboardSignals({ since: '2026-08-21' })).toHaveLength(0)
    expect(signals[0].pillars).toEqual([
      expect.objectContaining({ name: 'momentum', score: 90, available: true }),
    ])
    expect(portfolio).toMatchObject({
      totals: {
        openLots: 1,
        contributedCapitalUsd: 10,
        equityUsd: 10.5,
        portfolioReturn: 0.05,
      },
      lots: [expect.objectContaining({ symbol: 'AAPL', exitOrderStatus: null })],
      history: [expect.objectContaining({ contributedCapital: 10 })],
    })
    expect(portfolio.totals.excessVsSpyUsd).toBeCloseTo(0.3)
    expect(readDashboardBacktests()).toEqual([
      expect.objectContaining({
        id: 'backtest-1',
        datasetSha256: 'dataset-hash',
        tradeCount: 1,
        rejectionCount: 1,
        splitCount: 1,
        metrics: expect.objectContaining({ trades: 1 }),
      }),
    ])
    expect(readDashboardOperations()).toEqual({
      brokerReconciliation: expect.objectContaining({
        status: 'matched',
        expectedPositions: { AAPL: 0.05 },
        actualPositions: { AAPL: 0.05 },
      }),
      runs: [
        expect.objectContaining({
          id: 'operation-1',
          command: 'refresh-fundamentals',
          status: 'failed',
          errorType: 'ValueError',
          exceptionChain: [{ type: 'ValueError', message: 'provider returned invalid JSON' }],
        }),
      ],
      jobs: [],
      ingestions: [],
    })
  })
  test('uses the newest bounded snapshot history and marks missing valuation unavailable', () => {
    createFixtureDatabase(databasePath)
    process.env.STOCK_WATCH_DATABASE_PATH = databasePath
    const db = new DatabaseSync(databasePath)
    db.exec('DELETE FROM portfolio_snapshots')
    expect(readDashboardPortfolio()).toMatchObject({
      performanceAvailable: false,
      snapshotAt: null,
    })
    const insert = db.prepare('INSERT INTO portfolio_snapshots VALUES (?, ?, ?, 10, 0, 0)')
    db.exec('BEGIN')
    for (let i = 0; i < 1005; i++)
      insert.run(
        new Date(Date.UTC(2026, 8, 1, 0, i)).toISOString(),
        10 + i,
        i === 1004 ? null : 10 + i
      )
    db.exec('COMMIT')
    const result = readDashboardPortfolio()
    expect(result.history).toHaveLength(1000)
    expect(result.history[0].equity).toBe(15)
    expect(result.totals.equityUsd).toBe(1014)
    expect(result.totals.excessReturn).toBeNull()
    expect(result).toMatchObject({
      performanceAvailable: true,
      snapshotAt: new Date(Date.UTC(2026, 8, 1, 0, 1004)).toISOString(),
    })
    db.close()
  })

  test('pending reservations are not counted as filled capital or open positions', () => {
    createFixtureDatabase(databasePath)
    process.env.STOCK_WATCH_DATABASE_PATH = databasePath
    const db = new DatabaseSync(databasePath)
    db.exec(
      "UPDATE paper_trade_lots SET status='pending',entry_price=NULL,entry_quantity=NULL; UPDATE paper_orders SET status='accepted'"
    )
    expect(readDashboardPortfolio().totals).toMatchObject({
      openLots: 0,
      pendingLots: 1,
      deployedNotionalUsd: 0,
      reservedNotionalUsd: 10,
    })
    db.close()
  })

  test('exact scan filters and counts share Eastern-day boundaries while legacy dates remain UTC', () => {
    createFixtureDatabase(databasePath)
    process.env.STOCK_WATCH_DATABASE_PATH = databasePath
    const db = new DatabaseSync(databasePath)
    db.exec("UPDATE signals SET as_of='2026-08-21T02:00:00Z'")
    const filters = {
      since: '2026-08-20',
      until: '2026-08-20',
      timezone: 'America/New_York',
      scanRunId: 'scan-1',
    }
    expect(readDashboardSignals(filters)).toHaveLength(1)
    expect(readSignalSummary({ ...filters, offset: 50 })).toMatchObject({
      total: 1,
      companies: 1,
      scanRunId: 'scan-1',
    })
    expect(readDashboardSignals({ ...filters, timezone: undefined })).toHaveLength(0)
    expect(readSignalSummary({ ...filters, scanRunId: 'missing' }).total).toBe(0)
    db.close()
  })
})

function createFixtureDatabase(path: string) {
  const database = new DatabaseSync(path)
  database.exec(`
    CREATE TABLE strategy_versions (
      id TEXT PRIMARY KEY, name TEXT, status TEXT, created_at TEXT, promoted_at TEXT
    );
    CREATE TABLE scan_runs (
      id TEXT PRIMARY KEY, strategy_version_id TEXT, scan_type TEXT,
      scheduled_for TEXT, status TEXT, error TEXT
    );
    CREATE TABLE instruments (id INTEGER PRIMARY KEY, symbol TEXT, name TEXT);
    CREATE TABLE signals (
      id TEXT PRIMARY KEY, scan_run_id TEXT, instrument_id INTEGER,
      horizon_trading_days INTEGER, as_of TEXT, opportunity_score REAL,
      data_completeness REAL, risk_level TEXT, decision TEXT,
      explanation TEXT, reasons_json TEXT, strategy_version_id TEXT
    );
    CREATE TABLE signal_evaluations (signal_id TEXT, state TEXT, reason TEXT, checked_at TEXT);
    CREATE TABLE audit_events (id INTEGER PRIMARY KEY, entity_id TEXT, entity_type TEXT, occurred_at TEXT, event_type TEXT, payload_json TEXT);
    INSERT INTO audit_events VALUES (1, 'order-1', 'paper_order', '2026-08-20T20:16:00Z', 'paper_order_reconciled', '{"status":"filled"}');
    CREATE TABLE signal_components (
      signal_id TEXT, name TEXT, normalized_score REAL, weight REAL,
      weighted_points REAL, available INTEGER
    );
    CREATE TABLE paper_orders (
      id TEXT PRIMARY KEY, signal_id TEXT, status TEXT, notional_usd REAL, error TEXT
    );
    CREATE TABLE paper_trade_lots (
      id TEXT PRIMARY KEY, signal_id TEXT, instrument_id INTEGER,
      entry_order_id TEXT, horizon_trading_days INTEGER, status TEXT,
      entry_notional_usd REAL, entry_price REAL, entry_quantity REAL,
      opened_at TEXT, target_exit_at TEXT, closed_at TEXT, exit_price REAL,
      exit_quantity REAL, realized_return REAL, created_at TEXT
    );
    CREATE TABLE paper_exit_orders (
      id TEXT PRIMARY KEY, lot_id TEXT, status TEXT, error TEXT
    );
    CREATE TABLE signal_outcomes (
      signal_id TEXT, horizon_trading_days INTEGER, net_return REAL,
      excess_return REAL, beat_spy INTEGER, terminal_positive INTEGER, dataset_version TEXT
    );
    CREATE TABLE market_bars (
      instrument_id INTEGER, timestamp TEXT, timeframe TEXT, adjustment TEXT,
      provider TEXT, close REAL
    );
    CREATE TABLE portfolio_snapshots (
      observed_at TEXT, equity REAL, spy_value REAL, contributed_capital REAL,
      realized_pnl REAL, unrealized_pnl REAL
    );
    CREATE TABLE job_runs (
      id TEXT, job_type TEXT, status TEXT, scheduled_for TEXT,
      attempt INTEGER, error TEXT
    );
    CREATE TABLE data_ingestions (
      id INTEGER, dataset TEXT, provider TEXT, status TEXT, started_at TEXT,
      completed_at TEXT, row_count INTEGER, error TEXT
    );
    CREATE TABLE operation_runs (
      id TEXT, command TEXT, status TEXT, started_at TEXT, completed_at TEXT,
      heartbeat_at TEXT, progress_current INTEGER, progress_total INTEGER,
      message TEXT, context_json TEXT, result_json TEXT, error_type TEXT,
      error_message TEXT, exception_chain_json TEXT, traceback TEXT,
      host TEXT, process_id INTEGER
    );
    CREATE TABLE broker_account_snapshots (
      id INTEGER PRIMARY KEY, captured_at TEXT, status TEXT, cash REAL, equity REAL
    );
    CREATE TABLE broker_reconciliations (
      id INTEGER PRIMARY KEY, captured_at TEXT, account_snapshot_id INTEGER,
      status TEXT, expected_positions_json TEXT, actual_positions_json TEXT,
      discrepancies_json TEXT, corporate_actions_json TEXT
    );
    CREATE TABLE backtest_runs (
      id TEXT, strategy_version_id TEXT, status TEXT, dataset_version TEXT,
      dataset_sha256 TEXT, feature_set_version TEXT, survivorship_biased INTEGER,
      round_trip_cost_bps REAL, created_at TEXT, completed_at TEXT,
      metrics_json TEXT
    );
    CREATE TABLE backtest_trades (id INTEGER, backtest_run_id TEXT);
    CREATE TABLE backtest_rejections (id INTEGER, backtest_run_id TEXT);
    CREATE TABLE backtest_splits (id INTEGER, backtest_run_id TEXT);

    INSERT INTO strategy_versions VALUES (
      'strategy-v0', 'S&P 500 v0', 'development', '2026-08-20T00:00:00Z', NULL
    );
    INSERT INTO scan_runs VALUES (
      'scan-1', 'strategy-v0', 'close', '2026-08-20T20:15:00Z', 'succeeded', NULL
    );
    INSERT INTO instruments VALUES (1, 'AAPL', 'Apple Inc.');
    INSERT INTO signals VALUES (
      'signal-1', 'scan-1', 1, 21, '2026-08-20T20:15:00Z',
      86, 100, 'low', 'qualified', 'Transparent fixture explanation.', '[]', 'strategy-v0'
    );
    INSERT INTO signal_components VALUES (
      'signal-1', 'momentum', 90, 0.25, 22.5, 1
    );
    INSERT INTO paper_orders VALUES ('order-1', 'signal-1', 'filled', 10, NULL);
    INSERT INTO paper_trade_lots(
      id, signal_id, instrument_id, entry_order_id, horizon_trading_days,
      status, entry_notional_usd, entry_price, entry_quantity, opened_at,
      target_exit_at, closed_at, exit_price, exit_quantity, realized_return,
      created_at
    ) VALUES (
      'lot-1', 'signal-1', 1, 'order-1', 21, 'open', 10, 200, 0.05,
      '2026-08-20T13:45:00Z', NULL, NULL, NULL, NULL, NULL,
      '2026-08-20T13:45:00Z'
    );
    INSERT INTO market_bars VALUES (
      1, '2026-08-20', '1Day', 'all', 'alpaca', 210
    );
    INSERT INTO portfolio_snapshots VALUES (
      '2026-08-20T21:15:00Z', 10.5, 10.2, 10, 0, 0.5
    );
    INSERT INTO broker_account_snapshots VALUES (
      1, '2026-08-20T21:15:00Z', 'ACTIVE', 99990, 100010
    );
    INSERT INTO broker_reconciliations VALUES (
      1, '2026-08-20T21:15:00Z', 1, 'matched',
      '{"AAPL":0.05}', '{"AAPL":0.05}', '[]', '[]'
    );
    INSERT INTO backtest_runs VALUES (
      'backtest-1', 'strategy-v0', 'succeeded', 'fixture-v1', 'dataset-hash',
      'features-v0', 1, 10, '2026-08-20T20:00:00Z',
      '2026-08-20T20:01:00Z',
      '{"trades":1,"summary":{"positive_rate":1,"beat_spy_rate":1,"average_excess_return":0.02}}'
    );
    INSERT INTO backtest_trades VALUES (1, 'backtest-1');
    INSERT INTO backtest_rejections VALUES (1, 'backtest-1');
    INSERT INTO backtest_splits VALUES (1, 'backtest-1');
    INSERT INTO operation_runs VALUES (
      'operation-1', 'refresh-fundamentals', 'failed',
      '2026-08-20T20:00:00Z', '2026-08-20T20:01:00Z',
      '2026-08-20T20:01:00Z', 10, 503, 'operation failed', '{}', '{}',
      'ValueError', 'provider returned invalid JSON',
      '[{"type":"ValueError","message":"provider returned invalid JSON"}]',
      'Traceback fixture', 'fixture-host', 123
    );
  `)
  database.close()
}
