import 'server-only'
import { DatabaseSync } from 'node:sqlite'
import { existsSync } from 'node:fs'
import { researchSymbol } from './research-store'

export function companyContext(input: string) {
  const symbol = researchSymbol(input)
  const path = process.env.STOCK_WATCH_DATABASE_PATH
  if (!path || !existsSync(path)) throw Error('Company information is unavailable')
  const db = new DatabaseSync(path)
  try {
    // This is a tiny indexed projection/queue, never a CompanyFacts JSON scan.
    db.exec('PRAGMA busy_timeout=100')
    const now = new Date().toISOString()
    let row = db.prepare('SELECT * FROM company_context WHERE symbol=?').get(symbol)
    if (
      !row ||
      (!['queued', 'running'].includes(String(row.status)) && String(row.retry_after || '') <= now)
    ) {
      db.exec('BEGIN IMMEDIATE')
      try {
        const active = Number(
          db
            .prepare(
              "SELECT count(*) AS n FROM company_context WHERE status IN ('queued','running')"
            )
            .get()!.n
        )
        if (active < 20) {
          if (!row)
            db.prepare(
              "DELETE FROM company_context WHERE symbol IN (SELECT symbol FROM company_context WHERE status NOT IN ('queued','running') ORDER BY requested_at LIMIT max(0,(SELECT count(*) FROM company_context)-499))"
            ).run()
          db.prepare(
            `INSERT INTO company_context(symbol,status,requested_at) VALUES (?,'queued',?)
            ON CONFLICT(symbol) DO UPDATE SET status='queued',requested_at=excluded.requested_at,error=NULL
            WHERE company_context.status NOT IN ('queued','running') AND COALESCE(company_context.retry_after,'')<=excluded.requested_at`
          ).run(symbol, now)
        }
        db.exec('COMMIT')
      } catch (error) {
        db.exec('ROLLBACK')
        throw error
      }
      row = db.prepare('SELECT * FROM company_context WHERE symbol=?').get(symbol)
    }
    if (!row)
      return {
        symbol,
        status: 'unavailable',
        error: 'Company information is busy. Try again shortly.',
        data: null,
      }
    const data = row.payload_json ? JSON.parse(String(row.payload_json)) : null
    return {
      symbol,
      status: row.status,
      updatedAt: row.updated_at,
      retryAfter: row.retry_after,
      stale: Boolean(data && (row.status !== 'ready' || String(row.retry_after || '') <= now)),
      error: row.error,
      data,
    }
  } finally {
    db.close()
  }
}
