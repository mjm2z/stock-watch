import 'server-only'
import { DatabaseSync } from 'node:sqlite'
import { existsSync } from 'node:fs'
import { randomUUID } from 'node:crypto'

export class ResearchInputError extends Error {}
export function researchSymbol(value: unknown): string {
  const symbol = typeof value === 'string' ? value.trim().toUpperCase() : ''
  if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(symbol)) throw new ResearchInputError('Enter a valid ticker.')
  return symbol
}
function field(value: unknown, name: string, required = false): string {
  if (typeof value !== 'string' || value.length > 5000 || (required && !value.trim())) throw new ResearchInputError(`${name} must contain ${required ? '1–' : '0–'}5000 characters.`)
  return value.trim()
}
export function researchDatabase<T>(write: boolean, callback: (db: DatabaseSync) => T): T {
  const path = process.env.STOCK_WATCH_DATABASE_PATH?.trim()
  if (!path || !existsSync(path)) throw new Error('Research database is unavailable')
  // Only the explicit research mutations below use a writable connection.
  const db = new DatabaseSync(path, { readOnly: !write })
  try { db.exec('PRAGMA busy_timeout=3000; PRAGMA foreign_keys=ON'); return callback(db) }
  finally { db.close() }
}
export function readResearch(symbol?: string) {
  return researchDatabase(false, db => ({
    watchlist: db.prepare('SELECT ticker, added_at AS addedAt, notes FROM research_watchlist ORDER BY added_at DESC').all(),
    notes: symbol
      ? db.prepare('SELECT * FROM research_notes WHERE ticker=? ORDER BY created_at DESC, id DESC LIMIT 100').all(researchSymbol(symbol))
      : db.prepare('SELECT * FROM research_notes ORDER BY created_at DESC, id DESC LIMIT 100').all(),
  }))
}
export function writeResearch(body: Record<string, unknown>) {
  const ticker = researchSymbol(body.ticker)
  const at = new Date().toISOString()
  if (body.action === 'watch' || body.action === 'unwatch') {
    const notes = field(body.notes ?? '', 'Notes')
    return researchDatabase(true, db => {
      if (body.action === 'watch') db.prepare('INSERT INTO research_watchlist VALUES (?, ?, ?) ON CONFLICT(ticker) DO NOTHING').run(ticker, at, notes)
      else db.prepare('DELETE FROM research_watchlist WHERE ticker=?').run(ticker)
    })
  }
  if (body.action !== 'note') throw new ResearchInputError('Unknown research action.')
  const hypothesis = field(body.hypothesis, 'Hypothesis', true)
  const evidence = field(body.evidence ?? '', 'Evidence')
  const contrary = field(body.contrary_evidence ?? '', 'Contrary evidence')
  if (![5, 21, 63, 105].includes(Number(body.horizon))) throw new ResearchInputError('Choose a supported horizon.')
  const review = typeof body.review_on === 'string' ? body.review_on : ''
  if (!/^\d{4}-\d{2}-\d{2}$/.test(review) || !Number.isFinite(Date.parse(review)) || new Date(review).toISOString().slice(0,10) !== review) throw new ResearchInputError('Choose a valid review date.')
  if (!['open','supported','mixed','invalidated'].includes(String(body.assessment))) throw new ResearchInputError('Choose an assessment.')
  return researchDatabase(true, db => db.prepare('INSERT INTO research_notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)').run(
    randomUUID(), ticker, at, hypothesis, evidence, contrary, Number(body.horizon), review, String(body.assessment),
  ))
}
