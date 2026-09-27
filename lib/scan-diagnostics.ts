import 'server-only'
import { researchDatabase } from './research-store'
export function scanDiagnostics(scanId?: string) {
  return researchDatabase(false, (db) => {
    if (!db.prepare("SELECT 1 FROM sqlite_master WHERE name='scan_diagnostic_snapshots'").get())
      return null
    const row = scanId
      ? db
          .prepare('SELECT payload_json,captured_at FROM scan_diagnostic_snapshots WHERE scan_id=?')
          .get(scanId)
      : db
          .prepare(
            'SELECT d.payload_json,d.captured_at FROM scan_diagnostic_snapshots d JOIN scan_runs s ON s.id=d.scan_id ORDER BY s.scheduled_for DESC LIMIT 1'
          )
          .get()
    return row
      ? ({ ...JSON.parse(String(row.payload_json)), captured_at: row.captured_at } as Record<
          string,
          any
        >)
      : null
  })
}
