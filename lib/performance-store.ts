import 'server-only'
import { researchDatabase } from './research-store'
export function accountPerformance(asset: 'stocks' | 'bitcoin') {
  return researchDatabase(false, (db) => {
    if (!db.prepare("SELECT 1 FROM sqlite_master WHERE name='performance_results'").get())
      return {
        available: false,
        reason: 'Install the measurement migration and collect account valuations',
        result: null,
      }
    const row = db
      .prepare(
        'SELECT payload_json FROM performance_results WHERE scope=? ORDER BY as_of DESC LIMIT 1'
      )
      .get(asset + '_account')
    if (!row)
      return {
        available: false,
        reason:
          'Awaiting prospective account valuations; legacy fill cohorts are available separately',
        result: null,
      }
    const result = JSON.parse(String(row.payload_json)) as Record<string, any>
    const points = db
      .prepare(
        'SELECT at,details_json FROM performance_marks WHERE scope=? AND owner_id=? AND at<=? ORDER BY at DESC LIMIT 500'
      )
      .all(result.scope, result.owner, result.as_of)
      .reverse()
      .map((mark) => ({
        at: String(mark.at),
        index: JSON.parse(String(mark.details_json)).return_index as number | null,
      }))
    return {
      points,
      available: Boolean(result.available && result.intervals > 0),
      reason: result.reason as string | null,
      result,
    }
  })
}
