'use client'
import { useEffect, useState } from 'react'
import type { ActivityRow } from '@/lib/inspection-store'
export function ActivityWorkspace({
  asset,
  initialScope = 'manual',
  initialSymbol = '',
}: {
  asset: 'stocks' | 'bitcoin'
  initialScope?: string
  initialSymbol?: string
}) {
  const [filters, setFilters] = useState({
    scope: initialScope,
    symbol: initialSymbol,
    status: '',
    kind: '',
    account: '',
    owner: '',
    from: '',
    to: '',
  })
  const [before, setBefore] = useState(''),
    [data, setData] = useState<{ rows: ActivityRow[]; next: string | null; unavailable: string[] }>(
      { rows: [], next: null, unavailable: [] }
    ),
    [selected, setSelected] = useState<ActivityRow | null>(null),
    [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setData({ rows: [], next: null, unavailable: [] })
    const params = new URLSearchParams({ asset, ...filters, before })
    void fetch('/api/activity?' + params, { signal: controller.signal, cache: 'no-store' })
      .then(async (r) => {
        const result = await r.json()
        if (!r.ok) throw Error(result.error)
        return result
      })
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setData({ rows: [], next: null, unavailable: [e.message] })
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [asset, filters, before, refresh])
  const edit = (key: keyof typeof filters, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }))
    setBefore('')
    setSelected(null)
  }
  return (
    <main className="container mx-auto space-y-5 p-4 sm:p-8">
      <header>
        <h1 className="text-2xl font-semibold">
          Activity · {asset === 'bitcoin' ? 'Bitcoin' : 'Stocks'}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Recorded state transitions. Inspect an event for its exact time, ownership and retained
          evidence. No recorded event is different from a failed worker.
        </p>
      </header>
      <div className="flex flex-wrap gap-3">
        <label className="sw-field">
          Account scope
          <select value={filters.scope} onChange={(e) => edit('scope', e.target.value)}>
            <option value="manual">Manual allocation</option>
            <option value="automated">Automated systems</option>
            {asset === 'stocks' && <option value="scanner">Scanner</option>}
          </select>
        </label>
        {(['symbol', 'account', 'owner', 'status', 'kind'] as const).map((key) => (
          <label className="sw-field capitalize" key={key}>
            {key}
            <input
              value={filters[key]}
              onChange={(e) => edit(key, e.target.value)}
              placeholder={key === 'symbol' ? 'All symbols' : 'All'}
            />
          </label>
        ))}
        {(['from', 'to'] as const).map((key) => (
          <label className="sw-field capitalize" key={key}>
            {key}
            <input
              type="datetime-local"
              value={filters[key]}
              onChange={(e) => edit(key, e.target.value)}
            />
          </label>
        ))}
      </div>
      <div className="flex gap-3">
        <button
          className="sw-button"
          onClick={() => {
            setBefore('')
            setRefresh((n) => n + 1)
          }}
        >
          Latest activity
        </button>
        <a className="sw-button" href="/operations">
          Worker and feed health
        </a>
      </div>
      {loading && <p role="status">Loading events…</p>}
      {data.unavailable.map((s) => (
        <p role="alert" key={s}>
          {s}
        </p>
      ))}
      {!loading && !data.rows.length && !data.unavailable.length && (
        <p>
          No recorded transitions match these filters. Historical orders remain in their original
          ledgers; earlier transitions have not been reconstructed.
        </p>
      )}
      {!!data.rows.length && (
        <div className="overflow-auto rounded border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                {['Time (local)', 'Symbol', 'Account / owner', 'Event', 'Status', 'Evidence'].map(
                  (s) => (
                    <th key={s} className="p-3">
                      {s}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr className="border-t" key={row.id}>
                  <td className="whitespace-nowrap p-3">
                    <time title={row.at}>{new Date(row.at).toLocaleString()}</time>
                  </td>
                  <td className="p-3">{row.symbol}</td>
                  <td className="max-w-52 break-all p-3">
                    {row.account}
                    <br />
                    {row.owner}
                  </td>
                  <td className="p-3">{row.kind}</td>
                  <td className="p-3">{row.status}</td>
                  <td className="p-3">
                    <button className="underline" onClick={() => setSelected(row)}>
                      Inspect event
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.next && (
        <button className="sw-button" onClick={() => setBefore(data.next!)}>
          Older events
        </button>
      )}
      {selected && (
        <section className="sw-panel">
          <div className="flex justify-between">
            <h2>Event evidence</h2>
            <button className="sw-button" onClick={() => setSelected(null)}>
              Close
            </button>
          </div>
          <p className="my-3 break-all text-sm">
            {selected.at} · {selected.entity} · {selected.owner}
          </p>
          <p className="text-sm text-muted-foreground">
            Data → Rules → Decision → Qualification → Authorization → Order → Reconciliation. This
            event establishes only its recorded stage; missing input or rule evidence is
            unavailable.
          </p>
          <pre className="mt-4 max-h-96 overflow-auto text-xs">
            {JSON.stringify(selected.evidence, null, 2)}
          </pre>
        </section>
      )}
    </main>
  )
}
