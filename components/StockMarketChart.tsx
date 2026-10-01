'use client'
import { useEffect, useMemo, useRef, useState } from 'react'
import { LoaderCircle, X } from 'lucide-react'
import { ChartBar, InteractiveChart } from './MarketChart'
import { StockSearch } from './StockSearch'
import { ChartControls, ChartStyleSelect, type ChartStyle } from './ChartControls'
const palette = ['#6699ee', '#e7828e', '#54bda0', '#c59ae8', '#d9a64c']
type Series = { bars: ChartBar[]; loading: boolean; error?: string; partial?: boolean }
export function StockMarketChart() {
  const [symbols, setSymbols] = useState(['SPY']),
    [ready, setReady] = useState(false)
  const [range, setRange] = useState('3M'),
    [style, setStyle] = useState<ChartStyle>('candles'),
    [volume, setVolume] = useState(true)
  const [scale, setScale] = useState<'dollars' | 'percent'>('dollars'),
    [custom, setCustom] = useState({ start: '', end: '' })
  const [resetToken, setResetToken] = useState(0),
    [data, setData] = useState<Record<string, Series>>({}),
    [notice, setNotice] = useState(''),
    [retry, setRetry] = useState(0)
  const chosenScale = useRef(false),
    colors = useRef<Record<string, string>>({ SPY: palette[0] })
  const cache = useRef(new Map<string, Series>())
  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem('stockwatch-overview-symbols') || 'null')
      if (Array.isArray(stored)) {
        const list = [
          ...new Set(
            stored.filter(
              (s): s is string => typeof s === 'string' && /^[A-Z][A-Z0-9.-]{0,14}$/.test(s)
            )
          ),
        ].slice(0, 5)
        setSymbols(list)
        if (list.length > 1) {
          setStyle('line')
          setScale('percent')
        }
      }
    } catch {}
    setReady(true)
  }, [])
  useEffect(() => {
    if (ready) {
      try {
        localStorage.setItem('stockwatch-overview-symbols', JSON.stringify(symbols))
      } catch {}
    }
  }, [symbols, ready])
  for (const s of symbols)
    if (!colors.current[s])
      colors.current[s] =
        palette.find((c) => !symbols.some((t) => colors.current[t] === c)) || palette[0]
  useEffect(() => {
    if (!ready) return
    const controller = new AbortController()
    setData(() => Object.fromEntries(symbols.map((s) => [s, { bars: [], loading: true }])))
    for (const symbol of symbols) {
      const query = new URLSearchParams({
        range: range.toUpperCase(),
        adjustment: 'all',
        ...(range.toUpperCase() === 'CUSTOM' ? custom : {}),
      })
      const key = symbol + query.toString(),
        cached = cache.current.get(key)
      if (cached && retry === 0) {
        setData((old) => ({ ...old, [symbol]: cached }))
        continue
      }
      void fetch(`/api/stock/${encodeURIComponent(symbol)}/history?${query}`, {
        signal: controller.signal,
      })
        .then(async (r) => {
          const d = await r.json()
          if (!r.ok) throw Error(d.error || 'History unavailable')
          if (d.meta?.adjustment !== 'all')
            throw Error('Adjusted history unavailable from this provider')
          const next: Series = {
            bars: d.data.map((b: any) => ({ ...b, at: b.date })),
            loading: false,
            partial: d.meta.partial,
          }
          if (!controller.signal.aborted) {
            cache.current.set(key, next)
            if (cache.current.size > 50) cache.current.delete(cache.current.keys().next().value!)
            setData((old) => ({ ...old, [symbol]: next }))
          }
        })
        .catch((e) => {
          if (!controller.signal.aborted)
            setData((old) => ({ ...old, [symbol]: { bars: [], loading: false, error: e.message } }))
        })
    }
    return () => controller.abort()
  }, [symbols, range, custom, ready, retry])
  const loaded = useMemo(
    () =>
      symbols
        .filter((s) => data[s]?.bars.length)
        .map((name) => ({ name, bars: data[name].bars, color: colors.current[name] })),
    [symbols, data]
  )
  const plotted = useMemo(() => {
    if (scale === 'dollars' || !loaded.length) return loaded
    const sets = loaded.map((s) => new Set(s.bars.map((b) => b.at)))
    const baseline = loaded[0].bars.find((b) => sets.every((s) => s.has(b.at)))?.at
    if (!baseline) return []
    return loaded.map((s) => {
      const base = s.bars.find((b) => b.at === baseline)!.close
      return {
        ...s,
        bars: s.bars
          .filter((b) => b.at >= baseline)
          .map((b) => ({
            ...b,
            open: (b.open / base - 1) * 100,
            high: (b.high / base - 1) * 100,
            low: (b.low / base - 1) * 100,
            close: (b.close / base - 1) * 100,
          })),
      }
    })
  }, [loaded, scale])
  function add(ticker: string) {
    if (symbols.includes(ticker)) {
      setNotice(`${ticker} is already on the chart.`)
      return
    }
    if (symbols.length >= 5) {
      setNotice('Remove a stock to add another (five maximum).')
      return
    }
    if (symbols.length >= 1) {
      setStyle('line')
      if (symbols.length === 1) setVolume(false)
      if (!chosenScale.current) setScale('percent')
    }
    setSymbols([...symbols, ticker])
    setNotice('')
  }
  return (
    <section className="sw-panel sw-overview-chart" aria-label="Stocks price chart">
      <div className="sw-chart-top">
        <StockSearch
          className="sw-chart-search"
          onSelect={(s) => add(s.ticker)}
          addExactMatch
          clearOnSelect
        />
        <ul className="sw-chart-legend" aria-label="Selected stocks">
          {symbols.map((s) => (
            <li key={s}>
              <span className="sw-legend-indicator">
                {data[s]?.loading ? (
                  <LoaderCircle
                    size={14}
                    className="animate-spin motion-reduce:animate-none"
                    aria-label={`Loading ${s}`}
                  />
                ) : (
                  <span style={{ background: colors.current[s] }} />
                )}
              </span>
              <strong>{s}</strong>
              <button
                aria-label={`Remove ${s}`}
                onClick={() => {
                  setSymbols(symbols.filter((t) => t !== s))
                  delete colors.current[s]
                  setNotice('')
                }}
              >
                <X size={15} />
              </button>
            </li>
          ))}
        </ul>
      </div>
      {notice && (
        <p role="status" className="text-sm text-muted-foreground">
          {notice}
        </p>
      )}
      <ChartControls
        range={range}
        onRange={setRange}
        ranges={['1D', '1W', '1M', '3M', '6M', '1Y', '5Y', '10Y', '30Y']}
        custom={custom}
        onCustom={setCustom}
        style={style}
        onStyle={setStyle}
        volume={volume}
        onVolume={() => setVolume(!volume)}
        multiple={symbols.length > 1}
        hideStyle
      />
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <ChartStyleSelect style={style} onStyle={setStyle} multiple={symbols.length > 1} />
          <button className="sw-button" onClick={() => setResetToken((n) => n + 1)}>
            Reset view
          </button>
        </div>
        <div className="sw-segmented" role="radiogroup" aria-label="Price scale">
          {(['dollars', 'percent'] as const).map((v) => (
            <button
              key={v}
              role="radio"
              aria-checked={scale === v}
              aria-label={v === 'dollars' ? 'Dollar prices' : 'Percentage change'}
              onClick={() => {
                chosenScale.current = true
                setScale(v)
              }}
              onKeyDown={(e) => {
                if (['ArrowLeft', 'ArrowRight'].includes(e.key)) {
                  e.preventDefault()
                  chosenScale.current = true
                  setScale(v === 'dollars' ? 'percent' : 'dollars')
                  ;(
                    e.currentTarget.parentElement?.querySelector(
                      `[aria-label="${v === 'dollars' ? 'Percentage change' : 'Dollar prices'}"]`
                    ) as HTMLElement
                  )?.focus()
                }
              }}
            >
              {v === 'dollars' ? '$' : '%'}
            </button>
          ))}
        </div>
      </div>
      {symbols.map((s) =>
        data[s]?.error ? (
          <p role="alert" key={s} className="sw-notice">
            {s}: {data[s].error}{' '}
            <button className="underline" onClick={() => setRetry((n) => n + 1)}>
              Retry
            </button>
          </p>
        ) : data[s]?.partial ? (
          <p key={s} className="text-xs text-muted-foreground">
            {s}: Partial history · available from {data[s].bars[0]?.at.slice(0, 10)}
          </p>
        ) : null
      )}
      {plotted.length ? (
        <InteractiveChart
          key={range + custom.start + custom.end + scale + symbols.join(',')}
          bars={plotted[0].bars}
          comparisons={plotted.slice(1)}
          label={plotted[0].name}
          color={plotted[0].color}
          style={symbols.length > 1 ? 'line' : style}
          percent={scale === 'percent'}
          volume={volume && symbols.length === 1}
          showDataTable={false}
          externalReset
          resetToken={resetToken}
        />
      ) : (
        <div className="sw-chart-empty" role="status">
          {!symbols.length
            ? 'Search for a stock to start your chart.'
            : symbols.some((s) => data[s]?.loading)
              ? 'Loading price history…'
              : loaded.length
                ? 'No shared starting observation for this comparison.'
                : 'No history available for this range.'}
        </div>
      )}
      {volume &&
        symbols.length > 1 &&
        loaded.map((s) => (
          <div key={s.name} className="mt-3">
            <p className="text-xs font-medium" style={{ color: s.color }}>
              {s.name} volume
            </p>
            <InteractiveChart
              bars={s.bars}
              label={`${s.name} volume`}
              volume
              volumeOnly
              resetToken={resetToken}
              height={100}
              showDataTable={false}
            />
          </div>
        ))}
    </section>
  )
}
