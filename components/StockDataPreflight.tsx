'use client'
import { useEffect, useState } from 'react'

type Report = {
  canPrepare: boolean
  blockers: string[]
  usableBars: number
  usableInstruments: number
  instruments: number
  missingSectors: number
  barsWithoutCalendar: number
  benchmarkBars: number
  coveredStart: string | null
  coveredEnd: string | null
  note: string
}
export function StockDataPreflight({
  start,
  end,
  onReady,
}: {
  start: string
  end: string
  onReady: (value: boolean) => void
}) {
  const [state, setState] = useState<{ report?: Report; error?: string }>({})
  useEffect(() => {
    const controller = new AbortController()
    onReady(false)
    setState({})
    const timer = setTimeout(() => {
      void fetch('/api/systems/preflight?' + new URLSearchParams({ asset: 'stocks', start, end }), {
        cache: 'no-store',
        signal: controller.signal,
      })
        .then(async (response) => {
          const report = await response.json()
          if (!response.ok) throw Error(report.error || 'Data prerequisite check failed')
          if (!controller.signal.aborted) {
            setState({ report })
            onReady(report.canPrepare)
          }
        })
        .catch((error) => {
          if (!controller.signal.aborted)
            setState({ error: error instanceof Error ? error.message : 'Data check unavailable' })
        })
    }, 250)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [start, end, onReady])
  const report = state.report
  return (
    <div className="rounded-lg border border-white/10 p-4 text-sm" aria-live="polite">
      <h3 className="font-semibold">Stock data prerequisites</h3>
      {!report && (
        <p className="mt-2">{state.error || 'Checking captured data for this interval…'}</p>
      )}
      {report && (
        <>
          <p className="mt-2">
            {report.canPrepare
              ? 'Inputs present · research only'
              : 'Blocked · required inputs missing or ambiguous'}
          </p>
          {report.blockers.length > 0 && (
            <ul className="mt-2 list-disc pl-5">
              {report.blockers.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          <p className="mt-2">
            {report.usableInstruments}/{report.instruments} instruments ·{' '}
            {report.usableBars.toLocaleString()} usable raw bars
          </p>
          {report.coveredStart && report.coveredEnd && (
            <p>
              Captured session closes: {report.coveredStart} — {report.coveredEnd}
            </p>
          )}
          <p className="mt-2">
            {report.missingSectors} missing sectors · {report.barsWithoutCalendar} raw bars without
            calendar matches · {report.benchmarkBars} benchmark bars
          </p>
          <p className="sw-muted mt-2">{report.note}</p>
          {!report.canPrepare && (
            <p className="mt-2">
              Collect the missing raw history or calendar coverage through the reviewed worker
              procedure, then refresh this page. Existing scanner data stays available.
            </p>
          )}
        </>
      )}
    </div>
  )
}
