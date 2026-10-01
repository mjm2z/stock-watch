'use client'
import { useEffect, useState } from 'react'
export function CompactPerformance() {
  const [automated, setAutomated] = useState<any>(),
    [manual, setManual] = useState<any>()
  useEffect(() => {
    const controller = new AbortController()
    const load = async (url: string, setter: (v: any) => void) => {
      try {
        const r = await fetch(url, { signal: controller.signal, cache: 'no-store' })
        if (!r.ok) throw Error()
        const d = await r.json()
        if (!controller.signal.aborted) setter(d)
      } catch {
        if (!controller.signal.aborted) setter({ error: true })
      }
    }
    const refresh = () => {
      void load('/api/dashboard/performance?asset=stocks', setAutomated)
      void load('/api/manual-paper', setManual)
    }
    refresh()
    const timer = setInterval(refresh, 60000)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [])
  const allocation = manual?.balances
    ?.flatMap((b: any) => b.allocations || [])
    .find((a: any) => a.asset === 'stocks')
  const rows = [
    {
      label: 'Automated stocks',
      href: '/paper',
      value: automated?.available ? automated.result : null,
      pending: !automated,
    },
    {
      label: 'Manual stocks',
      href: '/manual-paper?asset=stocks',
      value:
        allocation && !allocation.unavailable_reason
          ? {
              equity: allocation.equity,
              return: allocation.net_return,
              maximum_drawdown: allocation.maximum_observed_drawdown,
              as_of: allocation.as_of,
            }
          : null,
      pending: !manual,
    },
  ]
  return (
    <section className="sw-panel sw-compact-performance" aria-label="Paper account performance">
      <h2>Paper account performance</h2>
      {rows.map((row) => (
        <div key={row.label} className="sw-performance-row">
          <a href={row.href} className="font-medium text-sm hover:underline">
            {row.label} <span aria-hidden="true">↗</span>
          </a>
          {row.value ? (
            <>
              <dl className="grid grid-cols-3 gap-3 mt-3">
                {[
                  [
                    'Equity',
                    row.value.equity == null
                      ? '—'
                      : Number(row.value.equity).toLocaleString('en-US', {
                          style: 'currency',
                          currency: 'USD',
                        }),
                  ],
                  [
                    'Return',
                    row.value.return == null ? '—' : (row.value.return * 100).toFixed(2) + '%',
                  ],
                  [
                    'Observed drawdown',
                    row.value.maximum_drawdown == null
                      ? '—'
                      : (row.value.maximum_drawdown * 100).toFixed(2) + '%',
                  ],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="text-base font-medium tabular-nums mt-1">{value}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-2 text-xs text-muted-foreground">
                As of{' '}
                {row.value.as_of
                  ? new Date(
                      typeof row.value.as_of === 'number' ? row.value.as_of * 1000 : row.value.as_of
                    ).toLocaleString()
                  : 'unavailable'}
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground mt-2">
              {row.pending ? 'Loading…' : 'Measurements unavailable'}
            </p>
          )}
        </div>
      ))}
    </section>
  )
}
