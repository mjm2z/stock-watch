import Link from 'next/link'
import { scanDiagnostics } from '@/lib/scan-diagnostics'
export function ScanFunnel() {
  let data: ReturnType<typeof scanDiagnostics> = null
  try {
    data = scanDiagnostics()
  } catch {
    /* Existing overview remains readable. */
  }
  return (
    <section id="scan-diagnostics" className="space-y-3 rounded-xl border bg-card p-5">
      <h2 className="text-lg font-semibold">Scan decisions and coverage</h2>
      {!data ? (
        <p className="text-sm text-muted-foreground">
          Detailed diagnostics will appear after the next scan or reviewed backfill.{' '}
          <Link className="underline" href="/operations">
            Existing liquidity diagnostics
          </Link>
        </p>
      ) : (
        <>
          <p className="text-sm">
            {data.unique_instruments} instruments · {data.assessments} horizon assessments · Job{' '}
            {data.job_status}
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['Usable assessments', data.usable_assessments],
              ['Score-qualified', data.score_qualified],
              ['Qualified after vetoes', data.veto_free_qualified],
              ['Entry checks allowed', data.execution_eligible],
              ['Submitted orders', data.submitted],
              ['Orders with fills', data.filled],
            ].map(([label, count]) => (
              <div key={String(label)}>
                <p className="text-xs text-muted-foreground">{label}</p>
                <strong>{count}</strong>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Frozen diagnostic captured {data.captured_at}; later fills may differ.{' '}
            {data.candidate_instruments ?? 'Unknown'} candidate instruments ·{' '}
            {data.candidate_failures ?? 'Unknown'} candidate failures.
          </p>
          <details>
            <summary className="cursor-pointer">Why assessments did not qualify</summary>
            <ul className="mt-2 space-y-1 text-sm">
              {Object.entries(data.primary).map(([reason, count]) => (
                <li key={reason}>
                  {reason.replaceAll('_', ' ')}: {String(count)}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">
              Primary reasons count each assessment once. {data.coverage_note} {data.execution_note}
            </p>
          </details>
        </>
      )}
    </section>
  )
}
