'use client'
import { useEffect, useState } from 'react'
import { ExternalLink, LoaderCircle } from 'lucide-react'

type Filing = {
  accession: string
  form: string
  filed: string
  accepted?: string
  period: string
  description: string
  url: string
  earningsRelated: boolean
}
type Metric = {
  label: string
  value: number | null
  unit: string
  start?: string
  end?: string
  periodLabel: string
  filed?: string
  accession?: string
  concept?: string
  url?: string
}
type Context = {
  symbol: string
  status: string
  stale?: boolean
  updatedAt?: string
  retryAfter?: string
  error?: string
  data?: {
    name: string
    cik: string
    kind: string
    filings: Filing[]
    metrics: Metric[]
    observedAt: string
    factsObservedAt?: string
    financialsNote?: string
  }
}
function sourceURL(value?: string) {
  return value &&
    /^https:\/\/www\.sec\.gov\/Archives\/edgar\/data\/\d+\/\d+\/\d{10}-\d{2}-\d{6}-index\.html$/.test(
      value
    )
    ? value
    : undefined
}
export function CompanyInformation({ symbols }: { symbols: string[] }) {
  const [selected, setSelected] = useState(symbols.at(-1) || '')
  const symbol = symbols.includes(selected) ? selected : symbols.at(-1) || ''
  const [state, setState] = useState<Context>()
  const [retry, setRetry] = useState(0)
  const [filter, setFilter] = useState('all')
  useEffect(() => {
    setSelected(symbols.at(-1) || '')
    setFilter('all')
  }, [symbols.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!symbol) return
    const controller = new AbortController()
    let canceled = false
    let timer: ReturnType<typeof setTimeout>
    let attempts = 0
    setState((previous) =>
      previous?.symbol === symbol
        ? { ...previous, status: 'queued', error: undefined, stale: Boolean(previous.data) }
        : undefined
    )
    async function load() {
      const timeout = setTimeout(() => controller.abort(), 20000)
      try {
        const response = await fetch(`/api/stock/${encodeURIComponent(symbol)}/company`, {
          signal: controller.signal,
        })
        const body = await response.json()
        if (!response.ok) throw Error(body.error || 'Company information is unavailable.')
        if (canceled) return
        setState(body)
        if (['queued', 'running'].includes(body.status) && ++attempts < 60)
          timer = setTimeout(load, 3000)
        else if (['queued', 'running'].includes(body.status))
          setState({
            ...body,
            error: 'Collection is taking longer than expected. Check again shortly.',
          })
      } catch (error) {
        if (!canceled)
          setState((previous) => ({
            ...(previous?.symbol === symbol ? previous : {}),
            symbol,
            status: 'unavailable',
            stale: Boolean(previous?.symbol === symbol && previous.data),
            error: controller.signal.aborted
              ? 'Company information request timed out. Check again shortly.'
              : error instanceof Error
                ? error.message
                : 'Company information is unavailable.',
          }))
      } finally {
        clearTimeout(timeout)
      }
    }
    void load()
    return () => {
      canceled = true
      controller.abort()
      clearTimeout(timer)
    }
  }, [symbol, retry])
  const current = state?.symbol === symbol ? state : undefined
  const data = current?.data
  const loading =
    symbol && (!current || (['queued', 'running'].includes(current.status) && !current.error))
  const filings = (data?.filings || []).filter((f) => filter !== 'earnings' || f.earningsRelated)
  return (
    <section className="sw-panel" aria-label="SEC company information">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Company information</h2>
          <p className="sw-muted">SEC filings and reported financials</p>
        </div>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Company ticker">
          {symbols.map((s) => (
            <button
              key={s}
              className="sw-button"
              aria-pressed={s === symbol}
              onClick={() => {
                setSelected(s)
                setFilter('all')
              }}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      {!symbol ? (
        <p className="sw-muted mt-4">Add a stock to the chart to view its SEC information.</p>
      ) : (
        <>
          <div className="min-h-8 mt-3 text-xs text-muted-foreground" role="status">
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" />
                Collecting {symbol} filings…
              </span>
            ) : current?.error ? (
              <span>
                {current.error}{' '}
                <button className="text-primary underline" onClick={() => setRetry((n) => n + 1)}>
                  Check again
                </button>
              </span>
            ) : data ? (
              `${data.name} · CIK ${data.cik}`
            ) : (
              'No company information available.'
            )}
            {data && (
              <p>
                {current?.stale ? 'Previously collected information · ' : ''}Filings checked{' '}
                {new Date(data.observedAt).toLocaleString()}
              </p>
            )}
          </div>
          {data && (
            <>
              {data.kind === 'fund' ? (
                <p className="sw-muted my-4">
                  Fund issuer filings · Corporate revenue and earnings metrics do not apply. Shared
                  issuers may report on multiple fund series.
                </p>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-3 my-4 lg:grid-cols-5">
                    {data.metrics.map((m) => (
                      <div key={m.label} className="rounded-lg border p-3">
                        <p className="text-xs text-muted-foreground">{m.label}</p>
                        <p className="my-2 text-lg font-medium tabular-nums">
                          {m.value === null
                            ? 'Unavailable'
                            : new Intl.NumberFormat('en-US', {
                                style: 'currency',
                                currency: 'USD',
                                notation: m.unit === 'USD/shares' ? 'standard' : 'compact',
                                maximumFractionDigits: 2,
                              }).format(m.value)}
                        </p>
                        {m.value !== null && (
                          <>
                            <p className="text-xs text-muted-foreground">
                              {m.periodLabel} · {m.start ? `${m.start} – ` : ''}
                              {m.end}
                            </p>
                            <a
                              className="text-xs text-primary hover:underline"
                              href={sourceURL(m.url)}
                              target="_blank"
                              rel="noopener noreferrer"
                              title={`${m.concept} · ${m.accession}`}
                            >
                              Filed {m.filed} ↗
                            </a>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                  <p className="sw-muted">
                    Latest reported annual figures; cash is a point-in-time balance. Periods may
                    differ. No inferred growth or earnings forecasts.
                  </p>
                  {data.factsObservedAt && (
                    <p className="sw-muted">
                      Financial facts collected {new Date(data.factsObservedAt).toLocaleString()}
                    </p>
                  )}
                  {data.financialsNote && <p className="sw-notice">{data.financialsNote}</p>}
                </>
              )}
              <div className="flex items-center justify-between gap-3 mt-5 mb-2">
                <h3 className="font-medium">Recent filings</h3>
                <select
                  aria-label="Filing filter"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="all">All recent filings</option>
                  <option value="earnings">Earnings disclosures</option>
                </select>
              </div>
              <ul className="divide-y max-h-80 overflow-auto">
                {filings.map((f) => (
                  <li key={f.accession} className="py-3 flex items-start justify-between gap-3">
                    <div>
                      <a
                        className="text-primary hover:underline inline-flex items-center gap-2"
                        href={sourceURL(f.url)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {f.form}
                        {f.earningsRelated ? ' · Earnings disclosure' : ''}
                        <ExternalLink size={12} />
                      </a>
                      <p className="text-xs text-muted-foreground">
                        {f.description || f.accession}
                        {f.period ? ` · Period ${f.period}` : ''}
                      </p>
                      {f.accepted && (
                        <p className="text-xs text-muted-foreground">
                          Accepted {new Date(f.accepted).toLocaleString()}
                        </p>
                      )}
                    </div>
                    <time className="text-xs text-muted-foreground whitespace-nowrap">
                      {f.filed}
                    </time>
                  </li>
                ))}
              </ul>
              {!filings.length && (
                <p className="sw-muted py-3">No matching filings in the recent SEC response.</p>
              )}
              <p className="sw-muted mt-3">
                Source: SEC EDGAR · Up to 20 recent reports. Earnings disclosures identify reported
                8-K Item 2.02 filings, not upcoming earnings dates. Open a filing to view its
                exhibits.
              </p>
            </>
          )}
        </>
      )}
    </section>
  )
}
