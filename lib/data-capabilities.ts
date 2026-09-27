import 'server-only'
import { researchDatabase } from './research-store'
const required = [
  'point_in_time_membership',
  'historical_sectors',
  'delisted_securities',
  'splits',
  'dividends',
  'spin_offs',
  'symbol_identity',
  'volume_adjustments',
  'missing_sessions',
  'revision_history',
]
export function dataCapabilities() {
  return researchDatabase(false, (db) => {
    const datasets = db
      .prepare(
        'SELECT id,asset,manifest_json FROM system_datasets ORDER BY created_at DESC LIMIT 20'
      )
      .all()
    const series = db.prepare("SELECT 1 FROM sqlite_master WHERE name='market_series'").get()
      ? db.prepare('SELECT * FROM market_series ORDER BY provider,feed,adjustment').all()
      : []
    const fundamentalReviews = db
      .prepare("SELECT 1 FROM sqlite_master WHERE name='source_provenance'")
      .get()
      ? db
          .prepare(
            "SELECT entity_id,recorded_at,payload_json FROM source_provenance WHERE entity_type='fundamental_review_v2' ORDER BY recorded_at DESC LIMIT 5"
          )
          .all()
          .map((r) => ({
            id: String(r.entity_id),
            recordedAt: String(r.recorded_at),
            review: JSON.parse(String(r.payload_json)),
          }))
      : []
    return {
      series,
      fundamentalReviews,
      datasets: datasets.map((row) => {
        const manifest = JSON.parse(String(row.manifest_json))
        return {
          id: row.id,
          asset: row.asset,
          provider: manifest.provider,
          capabilities: Object.fromEntries(
            required.map((name) => {
              const value = manifest.capabilities?.[name]
              return [
                name,
                (value?.status === 'verified' && value?.evidence) ||
                (value?.status === 'approximate' && value?.reason)
                  ? value
                  : { status: 'unavailable', reason: 'No verified source evidence retained' },
              ]
            })
          ),
          limitations: manifest.limitations || [],
          qualification:
            row.asset === 'stocks' && !manifest.corporate_actions_verified
              ? 'Research only: corporate actions unverified'
              : 'Review evidence and policy separately',
        }
      }),
      note: 'An adjustment option does not verify universe history, corporate actions, or publication timing. New SIP observations do not change the legacy scanner feed.',
    }
  })
}
