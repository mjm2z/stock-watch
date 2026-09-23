import { decisionReason } from '@/lib/decision-language'
import Link from 'next/link'
import { readResearchSummary, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'
export function ResearchQuality() {
  try {
    const summary = readResearchSummary()
    return (
      <section className="space-y-4 rounded-xl border bg-card p-5">
        <div>
          <h2 className="text-lg font-semibold">Research coverage & evaluation</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Latest completed scan: {summary.companies} companies · {summary.observations} horizon
            observations · {summary.qualifiedCompanies} qualified companies.
          </p>
        </div>
        <p className="text-sm text-muted-foreground">
          The same ranking score is evaluated over 5, 21, 63 and 105 trading days. Four observations
          for a company are not four independent forecasts. Data uses Alpaca IEX, a single exchange;
          volume is not consolidated market volume. Pillar coverage measures available scoring
          categories, not complete financial data. News with no matched articles can receive a
          neutral score.
        </p>
        <div className="grid gap-5 lg:grid-cols-2">
          <div>
            <h3 className="mb-3 text-sm font-semibold">Why companies were filtered out</h3>
            <ul className="space-y-2 text-sm">
              {summary.reasons.map((row) => (
                <li key={String(row.reason)} className="flex justify-between gap-3">
                  <Link
                    className="text-primary underline"
                    href={`/signals?scanRunId=${encodeURIComponent(summary.scanRunId ?? '')}&reason=${encodeURIComponent(String(row.reason))}`}
                  >
                    {decisionReason(String(row.reason))}
                  </Link>
                  <span className="whitespace-nowrap text-muted-foreground">
                    {Number(row.companies)} companies
                  </span>
                </li>
              ))}
            </ul>
            {!summary.reasons.length && (
              <p className="text-sm text-muted-foreground">No rejection reasons recorded yet.</p>
            )}
          </div>
          <div>
            <h3 className="mb-3 text-sm font-semibold">
              Completed paper-strategy research outcomes
            </h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th>Horizon</th>
                  <th>Samples</th>
                  <th>Companies</th>
                  <th>Positive</th>
                  <th>Beat SPY</th>
                </tr>
              </thead>
              <tbody>
                {[5, 21, 63, 105].map((horizon) => {
                  const row = summary.horizons.find((row) => Number(row.horizon) === horizon)
                  const rate = (value: unknown) =>
                    value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`
                  return (
                    <tr key={horizon} className="border-b">
                      <td className="py-2">{horizon}d</td>
                      <td>{Number(row?.observations ?? 0)}</td>
                      <td>{Number(row?.companies ?? 0)}</td>
                      <td>{rate(row?.positive)}</td>
                      <td>{rate(row?.beat_spy)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted-foreground">
              Only verified completed-session evaluations. Small and overlapping samples are
              descriptive, not calibrated probabilities. Modeled returns include costs; broker fills
              are shown in the paper portfolio.
            </p>
          </div>
        </div>
      </section>
    )
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable)
      return (
        <p className="text-sm text-muted-foreground">
          Research coverage is temporarily unavailable.
        </p>
      )
    throw error
  }
}
