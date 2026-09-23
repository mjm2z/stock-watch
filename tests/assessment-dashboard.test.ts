import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { readAssessmentDashboard } from '@/lib/worker-dashboard'

describe('assessment reporting', () => {
  let directory: string, db: DatabaseSync
  const original = process.env.STOCK_WATCH_DATABASE_PATH
  beforeEach(() => {
    directory = mkdtempSync(join(tmpdir(), 'assessment-'))
    const path = join(directory, 'worker.db')
    process.env.STOCK_WATCH_DATABASE_PATH = path
    db = new DatabaseSync(path)
    for (const file of readdirSync('worker/migrations')
      .filter((f) => f.endsWith('.sql'))
      .sort())
      db.exec(readFileSync(join('worker/migrations', file), 'utf8'))
    db.exec(`INSERT INTO strategy_versions(id,name,status,config_json,config_sha256) VALUES
      ('sp500-long-paper-v2','test','paper','{"portfolio":{"maximum_notional_usd":300,"maximum_sector_notional_usd":60},"entry_policy":{"enabled":true},"qualification":{"minimum_score":75}}','hash');
      INSERT INTO instruments(id,symbol,active,fractionable) VALUES (1,'AAPL',1,1),(2,'MSFT',1,1);
      INSERT INTO universe_snapshots(id,universe,effective_at,source,content_sha256) VALUES (1,'sp500','2026-09-17','fixture','hash');
      INSERT INTO universe_memberships VALUES (1,1);
      INSERT INTO feature_snapshots(id,instrument_id,as_of,feature_set_version,features_json,data_completeness) VALUES (1,1,'2026-09-17T20:15:00Z','test','{}',100);
      INSERT INTO scan_runs(id,strategy_version_id,universe_snapshot_id,scan_type,scheduled_for,data_cutoff,status) VALUES ('scan','sp500-long-paper-v2',1,'close','2026-09-17T20:15:00Z','2026-09-17T20:15:00Z','succeeded');`)
    for (const [id, horizon, decision, score] of [
      ['s1', 5, 'qualified', 85],
      ['s2', 21, 'qualified', 85],
      ['s3', 5, 'rejected', 72],
    ]) {
      db.prepare(
        `INSERT INTO signals(id,scan_run_id,strategy_version_id,instrument_id,feature_snapshot_id,horizon_trading_days,as_of,opportunity_score,data_completeness,risk_level,decision,explanation) VALUES (?,'scan','sp500-long-paper-v2',?,1,?,'2026-09-17T20:15:00Z',?,100,'low',?,'fixture')`
      ).run(id, id === 's3' ? 2 : 1, horizon, score, decision)
      db.prepare(`INSERT INTO assessment_reviews VALUES (?,'2026-09-17','{}','test')`).run(id)
      for (const variant of ['baseline-v1', 'without-news-v1'])
        db.prepare(`INSERT INTO shadow_assessments VALUES (?,?,?,?,'[]','{}','2026-09-17')`).run(
          id,
          variant,
          score,
          decision === 'qualified' ? 1 : 0
        )
    }
  })
  afterEach(() => {
    db.close()
    rmSync(directory, { recursive: true, force: true })
    if (original === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
    else process.env.STOCK_WATCH_DATABASE_PATH = original
  })
  test('keeps horizons distinct and rejected outcomes out of qualified results', () => {
    const result = readAssessmentDashboard()
    expect(result.variants).toHaveLength(4)
    expect(Object.getPrototypeOf(result.variants[0])).toBe(Object.prototype)
    expect(
      result.variants.find((row) => row.variant === 'baseline-v1' && row.horizon === 5)
    ).toMatchObject({ observations: 2, qualified: 1, matured: 0, net_return: null })
    expect(result.rejected).toHaveLength(1)
    expect(result.rejected[0]).toMatchObject({ observations: 1, matured: 0, horizon: 5 })
  })
  test('reports pending reservations and unknown sector as committed capital', () => {
    db.exec(`INSERT INTO paper_orders(id,signal_id,client_order_id,side,order_type,time_in_force,notional_usd,status) VALUES ('o1','s1','client','buy','market','day',15,'pending');
      INSERT INTO paper_trade_lots(id,signal_id,strategy_version_id,instrument_id,horizon_trading_days,entry_order_id,status,entry_notional_usd) VALUES ('l1','s1','sp500-long-paper-v2',1,5,'o1','pending',15);`)
    const result = readAssessmentDashboard()
    expect(result).toMatchObject({
      maximum: 300,
      sectorMaximum: 60,
      committed: 15,
      reserved: 15,
      policyEnabled: true,
    })
    expect(result.sectors).toEqual([{ sector: 'Unknown', committed: 15, reserved: 15, lots: 1 }])
  })
})
