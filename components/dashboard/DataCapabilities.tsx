import { dataCapabilities } from '@/lib/data-capabilities'
export function DataCapabilities() {
  let data: ReturnType<typeof dataCapabilities>
  try {
    data = dataCapabilities()
  } catch {
    return <p>Data capability report unavailable.</p>
  }
  return (
    <details className="rounded-xl border bg-card p-5">
      <summary className="cursor-pointer font-medium">
        Data sources and qualification limitations
      </summary>
      <p className="mt-3 text-sm text-muted-foreground">{data.note}</p>
      {!data.series.length && (
        <p className="mt-2 text-sm">
          Series provenance will be recorded by future ingestion. Historical feed coverage is not
          inferred.
        </p>
      )}
      <ul className="mt-3 space-y-2 text-sm">
        {data.series.map((s) => (
          <li key={String(s.id)}>
            {String(s.provider)} · {String(s.feed)} · {String(s.venue)} · {String(s.adjustment)} ·{' '}
            {String(s.timeframe)}
          </li>
        ))}
      </ul>
      {data.datasets.map((d) => (
        <details className="mt-3 border-t pt-2" key={String(d.id)}>
          <summary>
            {String(d.asset)} dataset {String(d.id).slice(0, 8)} · {d.qualification}
          </summary>
          <ul className="mt-2 text-sm">
            {Object.entries(d.capabilities).map(([key, v]) => (
              <li key={key}>
                {key.replaceAll('_', ' ')}: {String(v.status)} — {String(v.reason || v.evidence)}
              </li>
            ))}
          </ul>
        </details>
      ))}
      <details className="mt-3 border-t pt-2">
        <summary>Recent fundamentals shadow diagnostics</summary>
        <p className="text-sm text-muted-foreground">
          Conservative filing availability and fiscal-period checks; published scanner inputs remain
          unchanged.
        </p>
        {!data.fundamentalReviews.length && (
          <p className="text-sm">Awaiting the next scan with retained CompanyFacts.</p>
        )}
        {data.fundamentalReviews.map((r) => (
          <details className="mt-2" key={r.id}>
            <summary className="break-all text-sm">
              {r.id} · {r.recordedAt}
            </summary>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">
              {JSON.stringify(r.review, null, 2)}
            </pre>
          </details>
        ))}
      </details>
    </details>
  )
}
