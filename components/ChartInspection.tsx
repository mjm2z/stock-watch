'use client'
import { useCallback, useEffect, useState } from 'react'
import type { ChartEvent } from '@/lib/chart-events'
import type { ChartLevel, Layer } from '@/lib/inspection-store'
const layers: Layer[] = ['orders', 'positions', 'protections', 'systems', 'activity', 'preview']
export function ChartInspection({
  asset,
  symbol,
  compatible = true,
  children,
}: {
  asset: 'stocks' | 'bitcoin'
  symbol: string
  compatible?: boolean
  children: (
    levels: ChartLevel[],
    events: ChartEvent[],
    onEvent: (events: ChartEvent[]) => void
  ) => React.ReactNode
}) {
  const [preview, setPreview] = useState(''),
    [system, setSystem] = useState('')
  const [scope, setScope] = useState('manual'),
    [enabled, setEnabled] = useState<Layer[]>(['orders', 'positions', 'protections'])
  const [data, setData] = useState<{
    levels: ChartLevel[]
    unavailable: string[]
    asOf?: string
    previews?: any[]
    systems?: any[]
    previewEvents?: ChartEvent[]
  }>({ levels: [], unavailable: [] })
  const [events, setEvents] = useState<ChartEvent[]>([]),
    [eventDetail, setEventDetail] = useState<ChartEvent[]>([])
  const inspectEvents = useCallback((value: ChartEvent[]) => setEventDetail(value), [])
  const [selected, setSelected] = useState<ChartLevel | null>(null)
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('stockwatch-layers-' + asset) || 'null')
      if (Array.isArray(saved)) setEnabled(saved.filter((x) => layers.includes(x)))
    } catch {}
  }, [asset])
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setData({ levels: [], unavailable: [] })
    setSelected(null)
    setEvents([])
    setEventDetail([])
    async function load() {
      try {
        const r = await fetch(
          '/api/inspection?' + new URLSearchParams({ asset, symbol, scope, preview }),
          { signal: controller.signal, cache: 'no-store' }
        )
        const d = await r.json()
        if (!r.ok) throw Error(d.error)
        const a = await fetch(
          '/api/activity?' + new URLSearchParams({ asset, symbol, scope, limit: '200' }),
          { signal: controller.signal, cache: 'no-store' }
        )
        const history = await a.json()
        if (active) {
          setData(d)
          setEvents(
            (history.rows || []).map((row: any) => ({
              id: row.id,
              at: row.at,
              label: row.kind + ': ' + row.status,
              evidence: row,
            }))
          )
        }
      } catch {
        if (active) setData({ levels: [], unavailable: ['Inspection temporarily unavailable'] })
      }
    }
    void load()
    const timer = setInterval(load, 15000)
    return () => {
      active = false
      controller.abort()
      clearInterval(timer)
    }
  }, [asset, symbol, scope, preview])
  const visible = compatible
    ? data.levels.filter(
        (l) =>
          enabled.includes(l.layer) &&
          (scope !== 'automated' || !system || l.owner === system || l.layer === 'preview')
      )
    : []
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label>
          Ownership scope{' '}
          <select
            className="rounded border bg-background p-2"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            <option value="manual">Manual allocation</option>
            <option value="automated">Automated systems</option>
            {asset === 'stocks' && <option value="scanner">Scanner</option>}
          </select>
        </label>
        {layers.map((layer) => (
          <label key={layer} className="flex items-center gap-1 capitalize">
            <input
              type="checkbox"
              checked={enabled.includes(layer)}
              onChange={() => {
                const next = enabled.includes(layer)
                  ? enabled.filter((l) => l !== layer)
                  : [...enabled, layer]
                setEnabled(next)
                try {
                  localStorage.setItem('stockwatch-layers-' + asset, JSON.stringify(next))
                } catch {}
              }}
            />
            {layer}
          </label>
        ))}
      </div>
      {!compatible && (
        <p role="status" className="text-sm">
          Adjusted analytical prices: raw broker overlays disabled.
        </p>
      )}
      {data.unavailable.map((message) => (
        <p key={message} role="status" className="text-sm">
          {message}
        </p>
      ))}
      {children(
        visible,
        compatible
          ? [
              ...(enabled.includes('activity') ? events : []),
              ...(enabled.includes('preview') ? data.previewEvents || [] : []),
            ]
          : [],
        inspectEvents
      )}
      <p className="text-xs text-muted-foreground">
        Current overlays · {scope} · as of {data.asOf || 'unavailable'}. Lines do not assert that
        orders existed across this historical viewport. Visibility never changes execution.
      </p>
      <div className="flex flex-wrap gap-2">
        {visible.map((l) => (
          <button key={l.id} className="sw-button text-xs" onClick={() => setSelected(l)}>
            {l.layer}: {l.label}
            {l.price ? ` · $${l.price.toLocaleString()}` : ''}
          </button>
        ))}
      </div>
      {enabled.includes('systems') && scope === 'automated' && (
        <div>
          <label className="sw-field">
            Selected immutable system
            <select value={system} onChange={(e) => setSystem(e.target.value)}>
              <option value="">All owners</option>
              {data.systems?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} · {s.timeframe}
                </option>
              ))}
            </select>
          </label>
          {system && (
            <pre className="mt-2 max-h-48 overflow-auto text-xs">
              {JSON.stringify(
                data.systems?.find((s) => s.id === system),
                null,
                2
              )}
            </pre>
          )}
        </div>
      )}
      {enabled.includes('preview') && (
        <label className="sw-field">
          Preview / simulated overlay
          <select value={preview} onChange={(e) => setPreview(e.target.value)}>
            <option value="">None</option>
            {data.previews?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.created_at}
              </option>
            ))}
          </select>
        </label>
      )}
      {enabled.includes('systems') && (
        <p className="text-xs text-muted-foreground">
          System rule values must be recorded or explicitly simulated. Use Systems → Draft
          inspection for simulated rule evidence; missing historical decisions are unavailable.
        </p>
      )}
      {enabled.includes('preview') && (
        <p className="text-xs text-muted-foreground">
          Draft simulations appear in Systems → Historical preview, labelled Preview / simulated.
        </p>
      )}
      {enabled.includes('activity') && (
        <a
          className="inline-block text-sm underline"
          href={'/activity?' + new URLSearchParams({ asset, scope, symbol })}
        >
          Inspect exact activity timestamps and evidence
        </a>
      )}
      {eventDetail.length > 0 && (
        <section className="rounded border p-4">
          <div className="flex justify-between">
            <h3 className="font-semibold">Recorded events in this chart interval</h3>
            <button className="sw-button" onClick={() => setEventDetail([])}>
              Close events
            </button>
          </div>
          {eventDetail.map((event) => (
            <details key={event.id}>
              <summary>
                {event.at} · {event.label}
              </summary>
              <pre className="max-h-60 overflow-auto text-xs">
                {JSON.stringify(event.evidence, null, 2)}
              </pre>
            </details>
          ))}
        </section>
      )}
      {selected && (
        <section className="rounded border p-4">
          <div className="flex justify-between">
            <h3 className="font-semibold">{selected.label}</h3>
            <button className="sw-button" onClick={() => setSelected(null)}>
              Close inspector
            </button>
          </div>
          <dl className="my-3 text-sm">
            <dt>Owner / account</dt>
            <dd className="break-all">
              {selected.owner} / {selected.account}
            </dd>
            <dt>Source / price basis</dt>
            <dd>
              {selected.source} / {selected.basis}
            </dd>
            <dt>Recorded from</dt>
            <dd>{selected.validFrom || 'Unavailable'}</dd>
            <dt>As of</dt>
            <dd>{selected.asOf}</dd>
          </dl>
          <pre className="max-h-64 overflow-auto text-xs">
            {JSON.stringify(selected.evidence, null, 2)}
          </pre>
        </section>
      )}
    </div>
  )
}
