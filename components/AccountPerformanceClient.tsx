'use client'
import { AccountReturnCurve } from './AccountReturnCurve'
import { useEffect, useState } from 'react'
export function AccountPerformanceClient() {
  const [data, setData] = useState<any>()
  useEffect(() => {
    let active = true
    const load = () =>
      fetch('/api/dashboard/performance?asset=bitcoin')
        .then((r) => r.json())
        .then((d) => {
          if (active) setData(d)
        })
        .catch(() => {
          if (active) setData({ reason: 'Account measurements unavailable' })
        })
    void load()
    const timer = setInterval(load, 60000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [])
  const r = data?.result
  return (
    <section className="sw-panel space-y-2">
      <h2>Bitcoin account performance</h2>
      <p className="sw-muted">
        Whole paper account, including idle cash · Prospective broker observations
      </p>
      {data?.available && r ? (
        <p>
          Return {(r.return * 100).toFixed(2)}% · Observed drawdown{' '}
          {(r.maximum_drawdown * 100).toFixed(2)}% · Equity ${Number(r.equity).toFixed(2)}
        </p>
      ) : (
        <p className="sw-muted">{data?.reason || 'Loading account measurements…'}</p>
      )}
      {'points' in (data || {}) && data?.points && <AccountReturnCurve points={data.points} />}
      {r && (
        <p className="sw-muted">
          {r.since} — {r.as_of} · {r.observations} observations · {r.method}. {r.valuation}.
          Benchmark: {r.benchmark?.reason}.
        </p>
      )}
    </section>
  )
}
