import 'server-only'
import { DatabaseSync } from 'node:sqlite'
import { join, dirname } from 'node:path'
export function manualHealth(component: string) {
  const path =
    process.env.STOCK_WATCH_MANUAL_DATABASE ||
    join(
      dirname(process.env.STOCK_WATCH_DATABASE_PATH || '/var/lib/stock-watch/stock-watch.db'),
      'manual-paper.db'
    )
  const db = new DatabaseSync(path, { readOnly: true })
  try {
    const row = db.prepare('SELECT * FROM health WHERE component=?').get(component)
    const configured = Number(db.prepare('SELECT count(*) n FROM accounts').get()?.n) === 2
    const healthy = Boolean(row && !row.error && Date.now() / 1000 - Number(row.at) < 90)
    return { healthy, configured, component, observation: row || null }
  } finally {
    db.close()
  }
}
