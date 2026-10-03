import 'server-only'
import { DatabaseSync } from 'node:sqlite'
import { existsSync } from 'node:fs'
import { researchSymbol, ResearchInputError } from './research-store'
export function filingDetails(input: string, accession: string) {
  const symbol = researchSymbol(input)
  if (!/^\d{10}-\d{2}-\d{6}$/.test(accession)) throw new ResearchInputError('Invalid accession')
  const path = process.env.STOCK_WATCH_DATABASE_PATH
  if (!path || !existsSync(path)) throw Error('Unavailable')
  const db = new DatabaseSync(path)
  try {
    db.exec('PRAGMA busy_timeout=100')
    const issuer = db.prepare('SELECT payload_json FROM company_context WHERE symbol=?').get(symbol)
    const filings = issuer?.payload_json ? JSON.parse(String(issuer.payload_json)).filings : []
    if (!filings.some((f: { accession: string }) => f.accession === accession))
      throw new ResearchInputError('Filing is not in this issuer’s retained list')
    const now = new Date().toISOString()
    db.exec('BEGIN IMMEDIATE')
    try {
      const row = db
        .prepare('SELECT * FROM filing_details WHERE symbol=? AND accession=?')
        .get(symbol, accession)
      const active = Number(
        db
          .prepare("SELECT count(*) n FROM filing_details WHERE status IN ('queued','running')")
          .get()!.n
      )
      if (
        active < 5 &&
        (!row ||
          (!['queued', 'running'].includes(String(row.status)) &&
            String(row.retry_after || '') <= now))
      ) {
        db.prepare(
          "INSERT INTO filing_details(symbol,accession,status,requested_at) VALUES (?,?,'queued',?) ON CONFLICT(symbol,accession) DO UPDATE SET status='queued',requested_at=excluded.requested_at,error=NULL"
        ).run(symbol, accession, now)
      }
      db.exec('COMMIT')
    } catch (error) {
      db.exec('ROLLBACK')
      throw error
    }
    const row = db
      .prepare('SELECT * FROM filing_details WHERE symbol=? AND accession=?')
      .get(symbol, accession)
    return {
      status: row?.status || 'unavailable',
      error: row?.error || (!row ? 'Filing queue is busy. Check again shortly.' : null),
      updatedAt: row?.updated_at,
      retryAfter: row?.retry_after,
      stale: Boolean(row?.payload_json && row.status !== 'ready'),
      data: row?.payload_json ? JSON.parse(String(row.payload_json)) : null,
    }
  } finally {
    db.close()
  }
}
