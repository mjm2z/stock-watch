import { ExperimentComparison } from './ExperimentComparison'
import { readAssessmentDashboard } from '@/lib/worker-dashboard'
import { formatCurrency, formatTimestamp } from '@/lib/utils'
import { decisionReason } from '@/lib/decision-language'

const percent = (value: unknown) =>
  value === null || value === undefined ? '—' : `${(Number(value) * 100).toFixed(2)}%`
const variants: Record<string, string> = {
  'baseline-v1': 'Baseline weights + data checks',
  'horizon-weights-v1': 'Horizon-specific weights',
  'without-news-v1': 'Without news',
}

export function AssessmentControls({ research = false }: { research?: boolean }) {
  const data = readAssessmentDashboard()
  if (research)
    return (
      <section className="space-y-5 rounded-xl border bg-card p-5 shadow-sm">
        <div>
          <h2 className="text-xl font-semibold">Assessment experiments</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Modeled comparisons only. Experiments do not submit orders or change the active
            strategy.
          </p>
        </div>
        <details className="text-sm text-muted-foreground">
          <summary>How these comparisons are measured</summary>
          <p className="mt-2">
            Outcomes use next-session opening prices, finalized closes and 10 basis points of
            round-trip costs. Results stay separate by strategy version and holding period. Repeated
            and overlapping signals are correlated observations, not independent trials. These
            modeled results are separate from actual paper fills; they do not simulate portfolio
            limits or execution checks.
          </p>
        </details>
        {!data.variants.length ? (
          <p className="rounded-lg bg-muted p-4 text-sm">
            Waiting for the first scan with assessment reviews. Five-session outcomes need at least
            five completed trading sessions.
          </p>
        ) : (
          <ExperimentComparison rows={data.variants} />
        )}
        <details>
          <summary className="cursor-pointer text-sm font-medium">
            Rejected candidates and near-threshold research
          </summary>
          <p className="my-3 text-sm text-muted-foreground">
            Tracks what happened to skipped candidates. Near-threshold includes higher scores
            rejected for risk or missing data; it is not a recommendation to relax a gate.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr>
                  <th>Cohort / strategy</th>
                  <th>Horizon</th>
                  <th>Observed / matured</th>
                  <th>Avg. net</th>
                  <th>Vs. SPY</th>
                </tr>
              </thead>
              <tbody>
                {data.rejected.map((row, index) => (
                  <tr key={index} className="border-t">
                    <td className="py-3">
                      {String(row.cohort)}
                      <div className="text-xs text-muted-foreground">{String(row.strategy)}</div>
                    </td>
                    <td>{String(row.horizon)}d</td>
                    <td>
                      {String(row.observations)} / {String(row.matured)}
                    </td>
                    <td>{percent(row.net_return)}</td>
                    <td>{percent(row.excess_return)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
        <p className="text-xs text-muted-foreground">
          Sector-relative valuations and quarterly/TTM financial trends are not enabled. They
          require validated, comparable source coverage. No verified earnings calendar is connected;
          missing earnings data is shown as unknown.
        </p>
      </section>
    )
  return (
    <section className="space-y-5 rounded-xl border bg-card p-5 shadow-sm">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Allocation & entry checks</h2>
          <p className="text-sm text-muted-foreground">
            {data.policyEnabled ? 'Entry controls enabled' : 'Entry controls awaiting activation'} ·
            $5–$15 per order · $30 per stock
          </p>
        </div>
        <a className="text-sm text-primary" href="/research">
          View assessment experiments →
        </a>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <p className="text-sm text-muted-foreground">Committed / portfolio cap</p>
          <p className="text-2xl font-semibold">
            {formatCurrency(data.committed)}{' '}
            <span className="text-base text-muted-foreground">
              / {formatCurrency(data.maximum)}
            </span>
          </p>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">Reserved for pending entries</p>
          <p className="text-2xl font-semibold">{formatCurrency(data.reserved)}</p>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">Available allocation</p>
          <p className="text-2xl font-semibold">
            {formatCurrency(Math.max(0, data.maximum - data.committed))}
          </p>
        </div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full bg-primary"
          style={{ width: `${Math.min(100, (100 * data.committed) / data.maximum)}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Committed means entry cost for pending, open and closing lots across all strategy versions,
        not current market value or broker cash. Sector limit: {formatCurrency(data.sectorMaximum)}.
        Metadata covers {String(data.coverage.classified ?? 0)} of {String(data.coverage.total)}{' '}
        universe companies; unclassified stocks share one Unknown bucket.
      </p>
      {data.sectors.map((row) => (
        <div key={String(row.sector)} className="flex flex-wrap items-center gap-3 text-sm">
          <span className="w-full sm:w-44 sm:shrink-0">{String(row.sector)}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-primary/70"
              style={{
                width: `${Math.min(100, (100 * Number(row.committed)) / data.sectorMaximum)}%`,
              }}
            />
          </div>
          <span>
            {formatCurrency(Number(row.committed))} / {formatCurrency(data.sectorMaximum)}
          </span>
        </div>
      ))}
      <div>
        <h3 className="font-medium">Recent entry decisions</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Closing-scan candidates wait locally until the next session at 9:45 AM ET; unsubmitted
          entries expire by 10:00 AM. Opening-scan entries expire after 30 minutes. Scores are
          ranked before allocation; horizon priority is 21, 5, 63, then 105 sessions. Exit
          submission targets and actual fills are shown with each lot.
        </p>
      </div>
      {!data.entries.length ? (
        <p className="text-sm text-muted-foreground">
          No candidates have reached the new entry checks yet.
        </p>
      ) : (
        <div className="space-y-3">
          {data.entries.map((row) => (
            <details key={String(row.id)} className="rounded-lg border p-3 text-sm">
              <summary className="cursor-pointer">
                <strong>{String(row.symbol)}</strong> · {String(row.horizon)}d ·{' '}
                {formatCurrency(Number(row.notional_usd))} · {decisionReason(String(row.status))}
              </summary>
              <div className="mt-3 space-y-1 text-xs text-muted-foreground">
                <p>
                  Order: {decisionReason(String(row.status))} · Last checked:{' '}
                  {row.checked_at ? formatTimestamp(String(row.checked_at)) + ' ET' : 'Not checked'}
                </p>
                {row.status === 'pending' && row.next_check_at ? (
                  <p>
                    Next check: {formatTimestamp(String(row.next_check_at))} ET · Expires:{' '}
                    {formatTimestamp(String(row.expires_at))} ET
                  </p>
                ) : null}
                <p>Last entry check: {decisionReason(String(row.reason ?? 'Not recorded'))}</p>
                <EntryEvidence raw={row.details_json} />
              </div>
            </details>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Quotes use IEX, a single exchange. Earnings coverage is unknown unless a verified event is
        recorded; this release does not claim to screen every earnings event.
      </p>
    </section>
  )
}

function EntryEvidence({ raw }: { raw: unknown }) {
  if (!raw) return <p>No check details yet.</p>
  let evidence
  try {
    evidence = JSON.parse(String(raw))
    if (!evidence || typeof evidence !== 'object') throw new Error()
  } catch {
    return <p>Check evidence is unavailable.</p>
  }
  return (
    <div className="space-y-2">
      {typeof evidence.bid === 'number' && (
        <p>
          Bid / ask: {formatCurrency(evidence.bid)} / {formatCurrency(evidence.ask)} · Spread:{' '}
          {percent(evidence.spread_fraction)} · Quote age:{' '}
          {Number(evidence.quote_age_seconds).toFixed(0)} seconds
        </p>
      )}
      {typeof evidence.reference_price === 'number' && (
        <p>
          Assessment price: {formatCurrency(evidence.reference_price)} · Absolute price change:{' '}
          {percent(evidence.price_change_fraction)}
        </p>
      )}
      {evidence.earnings_coverage && (
        <p>Earnings coverage: unknown; no verified event feed connected.</p>
      )}
      <details>
        <summary className="cursor-pointer">Technical check details</summary>
        <pre className="mt-2 whitespace-pre-wrap break-all">
          {JSON.stringify(evidence, null, 2)}
        </pre>
      </details>
    </div>
  )
}
