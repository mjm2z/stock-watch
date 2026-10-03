'use client'
import { useEffect, useState } from 'react'
type Excerpt = { label: string; text: string; sections?: { title: string; text: string }[] }
function SourceExcerpt({ excerpt }: { excerpt: Excerpt }) {
  return (
    <>
      <h4 className="font-medium mt-3">{excerpt.label}</h4>
      <div
        tabIndex={0}
        role="region"
        aria-label="Filing source excerpt"
        className="max-h-80 overflow-y-auto whitespace-pre-wrap mt-2"
      >
        {excerpt.text || 'No extractable text. View the original filing.'}
      </div>
      {excerpt.sections?.map((section, i) => (
        <details key={i} className="mt-2">
          <summary className="text-primary cursor-pointer">{section.title}</summary>
          <div
            tabIndex={0}
            role="region"
            aria-label={section.title}
            className="max-h-80 overflow-y-auto whitespace-pre-wrap"
          >
            {section.text}
          </div>
        </details>
      ))}
    </>
  )
}
type Detail = {
  status: string
  error?: string
  stale?: boolean
  data?: {
    observedAt: string
    excerpt: Excerpt
    exhibit?: { source: string; excerpt: Excerpt }
    note?: string
    metrics: { label: string; value: number; unit: string; start?: string; end?: string }[]
  }
}
export function FilingDetails({ symbol, accession }: { symbol: string; accession: string }) {
  const [state, setState] = useState<Detail>()
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    let attempts = 0
    let canceled = false
    async function load() {
      const timeout = setTimeout(() => controller.abort(), 20000)
      try {
        const response = await fetch(
          `/api/stock/${encodeURIComponent(symbol)}/filings/${accession}`,
          { signal: controller.signal }
        )
        const body = await response.json()
        if (!response.ok) throw Error(body.error || 'Filing unavailable')
        if (controller.signal.aborted) return
        setState(body)
        if (['queued', 'running'].includes(body.status)) {
          if (++attempts < 60) timer = setTimeout(load, 3000)
          else
            setState({
              ...body,
              error: 'Collection is taking longer than expected. Check again shortly.',
            })
        }
      } catch (error) {
        if (!canceled)
          setState({
            status: 'unavailable',
            error: error instanceof Error ? error.message : 'Filing unavailable',
          })
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
  }, [symbol, accession, retry])
  return (
    <div className="mt-3 rounded-lg border p-3 text-sm">
      <div role="status" className="sw-muted">
        {!state || ['queued', 'running'].includes(state.status)
          ? 'Collecting filing details…'
          : null}
        {state?.error}{' '}
        {state?.error && (
          <button className="text-primary underline" onClick={() => setRetry((n) => n + 1)}>
            Check again
          </button>
        )}
      </div>
      {state?.data && (
        <>
          <p className="sw-muted">
            {state.stale ? 'Previously collected · ' : ''}SEC source text · Collected{' '}
            {new Date(state.data.observedAt).toLocaleString()}
          </p>
          {state.data.metrics.length > 0 && (
            <div className="my-3 grid gap-2 sm:grid-cols-2">
              {state.data.metrics.map((m, i) => (
                <div key={i}>
                  <strong>
                    {m.label}: {m.value.toLocaleString()} {m.unit}
                  </strong>
                  <p className="sw-muted">
                    {m.start ? `${m.start} – ` : 'As of '}
                    {m.end}
                  </p>
                </div>
              ))}
            </div>
          )}
          <p className="sw-muted">
            Figures above belong to this exact filing accession; comparative periods may be
            included. {state.data.note}
          </p>
          <SourceExcerpt excerpt={state.data.excerpt} />
          {state.data.exhibit && (
            <>
              <h4 className="font-semibold mt-4">Earnings-release exhibit · SEC source text</h4>
              <SourceExcerpt excerpt={state.data.exhibit.excerpt} />
            </>
          )}
          <p className="sw-muted mt-2">
            Excerpt only, not a summary or the complete filing. Tables may lose their original
            layout. View the original for exhibits and full context.
          </p>
        </>
      )}
    </div>
  )
}
