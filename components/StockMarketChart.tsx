'use client'
import { useEffect, useMemo, useState } from 'react'
import { ChartBar, InteractiveChart } from './MarketChart'
import { ChartInspection } from './ChartInspection'
export function StockMarketChart() {
  const [symbol, setSymbol] = useState('SPY'),
    [entry, setEntry] = useState('SPY'),
    [watchlist, setWatchlist] = useState(['SPY'])
  const [range, setRange] = useState('3M'),
    [candles, setCandles] = useState(true),
    [volume, setVolume] = useState(true),
    [basis, setBasis] = useState('raw')
  const [custom, setCustom] = useState({ start: '', end: '' }),
    [dates, setDates] = useState({ start: '', end: '' }),
    [resolution, setResolution] = useState('')
  const [compare, setCompare] = useState(''),
    [comparisonSymbols, setComparisonSymbols] = useState<string[]>([])
  const [data, setData] = useState<{
      bars: ChartBar[]
      meta?: any
      comparisons: { name: string; bars: ChartBar[] }[]
    }>({ bars: [], comparisons: [] }),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(true)
  useEffect(() => {
    try {
      const list = JSON.parse(localStorage.getItem('stockwatch-chart-watchlist') || 'null')
      if (Array.isArray(list))
        setWatchlist(list.filter((s) => /^[A-Z][A-Z0-9.-]{0,14}$/.test(s)).slice(0, 20))
    } catch {}
  }, [])
  useEffect(() => {
    if (range === 'CUSTOM' && (!custom.start || !custom.end)) return
    const controller = new AbortController()
    setLoading(true)
    setError('')
    setData({ bars: [], comparisons: [] })
    async function history(ticker: string) {
      const r = await fetch(
        `/api/stock/${encodeURIComponent(ticker)}/history?` +
          new URLSearchParams({
            range,
            adjustment: basis,
            ...(resolution ? { timeframe: resolution } : {}),
            ...(range === 'CUSTOM' ? custom : {}),
          }),
        { signal: controller.signal }
      )
      const d = await r.json()
      if (!r.ok) throw Error(`${ticker}: ${d.error}`)
      return { bars: d.data.map((b: any) => ({ ...b, at: b.date })) as ChartBar[], meta: d.meta }
    }
    void Promise.all([
      history(symbol),
      ...comparisonSymbols
        .filter((s) => s !== symbol)
        .map(async (s) => ({ name: s, ...(await history(s)) })),
    ])
      .then(([main, ...others]) => {
        if (!controller.signal.aborted)
          setData({ ...main, comparisons: others as { name: string; bars: ChartBar[] }[] })
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [symbol, range, basis, comparisonSymbols, custom, resolution])
  const normalized = useMemo(() => {
    // Same exact available timestamps and common start; never fill missing prices.
    const all = [{ name: symbol, bars: data.bars }, ...data.comparisons]
    if (all.length < 2) return []
    const maps = all.map((s) => new Map(s.bars.map((b) => [b.at, b])))
    const times = data.bars.map((b) => b.at).filter((t) => maps.every((m) => m.has(t)))
    return all.map((s, i) => ({
      name: s.name,
      bars: times.map((t) => {
        const b = maps[i].get(t)!
        const close = (b.close / maps[i].get(times[0])!.close - 1) * 100
        return { ...b, open: close, high: close, low: close, close }
      }),
    }))
  }, [data, symbol])
  return (
    <section className="sw-panel space-y-4">
      <div>
        <h2 className="text-xl font-semibold">Stocks chart</h2>
        <p className="text-sm text-muted-foreground">
          Focus on one instrument; compare up to five others. Display history is separate from
          strategy decision cadence.
        </p>
      </div>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          const value = entry.trim().toUpperCase()
          if (!/^[A-Z][A-Z0-9.-]{0,14}$/.test(value)) {
            setError('Enter a stock symbol')
            return
          }
          setSymbol(value)
          const next = [...new Set([...watchlist, value])].slice(-20)
          setWatchlist(next)
          try {
            localStorage.setItem('stockwatch-chart-watchlist', JSON.stringify(next))
          } catch {}
        }}
      >
        <label className="sw-field">
          Symbol
          <input value={entry} onChange={(e) => setEntry(e.target.value)} maxLength={15} />
        </label>
        <button className="sw-button">Show & save</button>
        {watchlist.map((s) => (
          <button
            type="button"
            key={s}
            className="sw-button"
            aria-pressed={s === symbol}
            onClick={() => {
              setSymbol(s)
              setEntry(s)
            }}
          >
            {s}
          </button>
        ))}
      </form>
      <div className="flex flex-wrap gap-3 text-sm">
        <label>
          Range{' '}
          <select
            value={range}
            onChange={(e) => setRange(e.target.value)}
            className="rounded border bg-background p-2"
          >
            {['1D', '1W', '1M', '3M', '1Y', '5Y', 'CUSTOM'].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label>
          Resolution{' '}
          <select
            className="rounded border bg-background p-2"
            value={resolution}
            onChange={(e) => setResolution(e.target.value)}
          >
            <option value="">Automatic</option>
            <option value="5Min">5 minutes</option>
            <option value="1Hour">Hourly</option>
            <option value="1Day">Daily</option>
          </select>
        </label>
        <label>
          Price basis{' '}
          <select
            className="rounded border bg-background p-2"
            value={basis}
            onChange={(e) => setBasis(e.target.value)}
          >
            <option value="raw">Raw · broker levels</option>
            <option value="all">Adjusted · analysis only</option>
          </select>
        </label>
        <label>
          <input type="checkbox" checked={candles} onChange={(e) => setCandles(e.target.checked)} />{' '}
          Candlesticks
        </label>
        <label>
          <input type="checkbox" checked={volume} onChange={(e) => setVolume(e.target.checked)} />{' '}
          Volume
        </label>
      </div>
      {range === 'CUSTOM' && (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            setCustom({ start: dates.start + 'T00:00:00Z', end: dates.end + 'T00:00:00Z' })
          }}
        >
          <label className="sw-field">
            From (UTC)
            <input
              required
              type="date"
              value={dates.start}
              onChange={(e) => setDates((d) => ({ ...d, start: e.target.value }))}
            />
          </label>
          <label className="sw-field">
            Until, exclusive (UTC)
            <input
              required
              type="date"
              value={dates.end}
              onChange={(e) => setDates((d) => ({ ...d, end: e.target.value }))}
            />
          </label>
          <button className="sw-button">Apply dates</button>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
      {loading && <p role="status">Loading {symbol} history…</p>}
      {!!data.bars.length && (
        <ChartInspection
          asset="stocks"
          symbol={symbol}
          compatible={data.meta?.adjustment === 'raw'}
        >
          {(levels, events, onEvent) => (
            <InteractiveChart
              events={events}
              onEvent={onEvent}
              key={symbol + range + basis}
              bars={data.bars}
              candles={candles}
              volume={volume}
              label={symbol}
              levels={levels}
            />
          )}
        </ChartInspection>
      )}
      <p className="text-xs text-muted-foreground">
        {data.meta?.provider || 'Source unavailable'} ·{' '}
        {data.meta?.resolution || 'resolution unavailable'} · {data.meta?.adjustment || basis}{' '}
        prices · collected {data.meta?.asOf || 'unavailable'} · {data.meta?.from} – {data.meta?.to}
      </p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          const symbols = [...new Set(compare.toUpperCase().split(/[ ,]+/).filter(Boolean))]
          if (symbols.length > 5 || symbols.some((s) => !/^[A-Z][A-Z0-9.-]{0,14}$/.test(s))) {
            setError('Choose up to five valid comparison symbols')
            return
          }
          setComparisonSymbols(symbols)
        }}
      >
        <label className="sw-field">
          Compare symbols (comma separated)
          <input
            value={compare}
            placeholder="QQQ, DIA"
            onChange={(e) => setCompare(e.target.value)}
          />
        </label>
        <button className="sw-button">Apply comparison</button>
      </form>
      {normalized.length > 1 && (
        <div>
          <h3 className="font-semibold">
            Aligned price return · {normalized.map((s) => s.name).join(', ')}
          </h3>
          <p className="text-xs text-muted-foreground">
            Common observed timestamps, first common close = 0%. Price returns exclude trading
            costs; this is not a funding-matched strategy benchmark.
          </p>
          <InteractiveChart
            key={symbol + range + basis + compare}
            bars={normalized[0].bars}
            percent
            label={symbol}
            comparisons={normalized.slice(1)}
          />
        </div>
      )}
    </section>
  )
}
