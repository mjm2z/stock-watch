'use client'
import { useEffect, useRef, useState } from 'react'
import { groupChartEvents, type ChartEvent } from '@/lib/chart-events'
import { ChartControls, type ChartStyle } from './ChartControls'
import type { ChartLevel } from '@/lib/inspection-store'
import type { Time, IChartApi, IRange, ISeriesApi, IPriceLine } from 'lightweight-charts'
export type ChartBar = {
  at: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}
type HistoryResponse = {
  bars: ChartBar[]
  status: string
  observedAt?: string
  coverageStart?: string
  coverageEnd?: string
  resolution?: string
  error?: string
  gaps?: number
  partial?: boolean
  refreshing?: boolean
  stale?: boolean
}
const NO_EVENTS: ChartEvent[] = []
const NO_LEVELS: ChartLevel[] = []
const NO_COMPARISONS: { name: string; bars: ChartBar[] }[] = []
export function InteractiveChart({
  bars,
  candles = false,
  volume = false,
  label = 'Price',
  height = 360,
  percent = false,
  levels = NO_LEVELS,
  comparisons = NO_COMPARISONS,
  events = NO_EVENTS,
  onEvent,
  style,
  color,
  showDataTable = true,
  volumeOnly = false,
}: {
  bars: ChartBar[]
  style?: ChartStyle
  color?: string
  showDataTable?: boolean
  volumeOnly?: boolean
  candles?: boolean
  volume?: boolean
  label?: string
  height?: number
  percent?: boolean
  levels?: ChartLevel[]
  events?: ChartEvent[]
  onEvent?: (events: ChartEvent[]) => void
  comparisons?: { name: string; bars: ChartBar[]; color?: string }[]
}) {
  const chartStyle = style || (candles ? 'candles' : 'line')
  const ohlc = chartStyle !== 'line'
  const [tablePage, setTablePage] = useState(0)
  const primary = useRef<ISeriesApi<'Line' | 'Candlestick' | 'Bar'> | null>(null)
  const priceLines = useRef<IPriceLine[]>([])
  const [chartGeneration, setChartGeneration] = useState(0)
  const viewport = useRef<IRange<Time> | null>(null)
  const container = useRef<HTMLDivElement>(null),
    chart = useRef<IChartApi>(),
    [hover, setHover] = useState<ChartBar | null>(null),
    [theme, setTheme] = useState('dark')
  useEffect(() => {
    const update = () => setTheme(document.documentElement.dataset.theme || 'dark')
    update()
    const o = new MutationObserver(update)
    o.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => o.disconnect()
  }, [])
  useEffect(() => {
    if (!container.current) return
    let disposed = false
    let dispose = () => {}
    void import('lightweight-charts').then(
      ({
        createChart,
        ColorType,
        CrosshairMode,
        LineSeries,
        CandlestickSeries,
        HistogramSeries,
        BarSeries,
      }) => {
        if (disposed || !container.current) return
        const dark = theme === 'dark',
          c = createChart(container.current, {
            height,
            width: container.current.clientWidth,
            layout: {
              attributionLogo: false,
              background: { type: ColorType.Solid, color: dark ? '#181c22' : '#ffffff' },
              textColor: dark ? '#929cab' : '#657184',
            },
            grid: {
              vertLines: { color: dark ? '#222832' : '#eef1f5' },
              horzLines: { color: dark ? '#222832' : '#eef1f5' },
            },
            crosshair: { mode: CrosshairMode.Normal },
            timeScale: { timeVisible: true, secondsVisible: false },
            handleScroll: { vertTouchDrag: false },
            localization: { locale: 'en-US' },
          })
        chart.current = c
        const sorted = [
          ...new Map(
            bars
              .filter((b) => Number.isFinite(Date.parse(b.at)) && Number.isFinite(b.close))
              .map((b) => [Math.floor(Date.parse(b.at) / 1000), b])
          ).entries(),
        ].sort((a, b) => a[0] - b[0])
        const byTime = new Map(sorted)
        const series = ohlc
          ? c.addSeries(chartStyle === 'bars' ? BarSeries : CandlestickSeries, {
              upColor: chartStyle === 'hollow' ? 'transparent' : '#8cd5bc',
              downColor: '#ee909b',
              borderVisible: chartStyle === 'hollow',
              borderUpColor: '#8cd5bc',
              borderDownColor: '#ee909b',
              wickUpColor: '#8cd5bc',
              wickDownColor: '#ee909b',
            })
          : c.addSeries(LineSeries, {
              color: color || (dark ? '#a8bcff' : '#5068d4'),
              lineWidth: 2,
            })
        primary.current = series
        setChartGeneration((g) => g + 1)
        if (percent)
          series.applyOptions({ priceFormat: { type: 'percent', precision: 2, minMove: 0.01 } })
        if (volumeOnly) series.applyOptions({ visible: false })
        if (ohlc)
          series.setData(
            sorted.map(([time, b]) => ({
              time: time as Time,
              open: b.open,
              high: b.high,
              low: b.low,
              close: b.close,
            }))
          )
        else series.setData(sorted.map(([time, b]) => ({ time: time as Time, value: b.close })))
        for (const [i, comparison] of comparisons.entries()) {
          const points = [
            ...new Map(
              comparison.bars
                .filter((b) => Number.isFinite(b.close))
                .map((b) => [Math.floor(Date.parse(b.at) / 1000), b.close])
            ).entries(),
          ].sort((a, b) => a[0] - b[0])
          const overlay = c.addSeries(LineSeries, {
            title: comparison.name,
            priceScaleId: 'right',
            color:
              comparison.color || ['#f4c77a', '#ee909b', '#8cd5bc', '#c6a5f4', '#78cddd'][i % 5],
            lineWidth: 1,
            priceFormat: { type: percent ? 'percent' : 'price' },
          })
          overlay.setData(points.map(([time, value]) => ({ time: time as Time, value })))
        }
        if (volume) {
          const v = c.addSeries(HistogramSeries, {
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
          })
          v.priceScale().applyOptions({
            scaleMargins: { top: volumeOnly ? 0.08 : 0.82, bottom: 0 },
          })
          v.setData(
            sorted.map(([time, b]) => ({
              time: time as Time,
              value: b.volume,
              color: b.close >= b.open ? '#8cd5bc40' : '#ee909b40',
            }))
          )
          series.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.24 } })
        }
        c.subscribeCrosshairMove((p) =>
          setHover(typeof p.time === 'number' ? byTime.get(p.time) || null : null)
        )
        if (viewport.current) c.timeScale().setVisibleRange(viewport.current)
        else c.timeScale().fitContent()
        const resize = new ResizeObserver(() => {
          if (container.current) c.applyOptions({ width: container.current.clientWidth })
        })
        resize.observe(container.current)
        dispose = () => {
          viewport.current = c.timeScale().getVisibleRange()
          resize.disconnect()
          primary.current = null
          priceLines.current = []
          c.remove()
          chart.current = undefined
        }
      }
    )
    return () => {
      disposed = true
      dispose()
    }
  }, [bars, chartStyle, ohlc, volume, theme, height, percent, comparisons, color, volumeOnly])
  useEffect(() => {
    const series = primary.current
    if (!series) return
    for (const line of priceLines.current) series.removePriceLine(line)
    priceLines.current = levels
      .filter((l) => l.price && Number.isFinite(l.price))
      .map((l) =>
        series.createPriceLine({
          price: l.price!,
          title: l.label,
          color: l.layer === 'protections' ? '#ee909b' : '#8cd5bc',
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
        })
      )
  }, [levels, chartGeneration])
  useEffect(() => {
    const series = primary.current,
      c = chart.current
    if (!series || !c) return
    let disposed = false
    let cleanup = () => {}
    void import('lightweight-charts').then(({ createSeriesMarkers }) => {
      if (disposed) return
      const times = [
        ...new Set(bars.map((b) => Math.floor(Date.parse(b.at) / 1000)).filter(Number.isFinite)),
      ].sort((a, b) => a - b)
      const groups = groupChartEvents(times, events)
      const markers = createSeriesMarkers(
        series,
        [...groups.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([time, list]) => ({
            time: time as Time,
            position: 'aboveBar' as const,
            shape: 'circle' as const,
            color: '#f4c77a',
            text: list.length > 1 ? `${list.length} events` : list[0].label,
          }))
      )
      const click = (p: { time?: Time }) => {
        if (typeof p.time === 'number' && groups.has(p.time)) onEvent?.(groups.get(p.time)!)
      }
      c.subscribeClick(click)
      cleanup = () => {
        if (chart.current === c) {
          c.unsubscribeClick(click)
          markers.detach()
        }
      }
    })
    return () => {
      disposed = true
      cleanup()
    }
  }, [events, bars, onEvent, chartGeneration])
  return (
    <div>
      {!volumeOnly && (
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="min-h-5 text-xs text-muted-foreground" aria-live="off">
            {hover && percent
              ? `${new Date(hover.at).toLocaleString()} · ${label} ${hover.close.toFixed(2)}%`
              : hover
                ? `${new Date(hover.at).toLocaleString()} · O $${hover.open.toLocaleString()} · H $${hover.high.toLocaleString()} · L $${hover.low.toLocaleString()} · C $${hover.close.toLocaleString()}`
                : 'Hover or touch the chart to inspect a point'}
          </div>
          <button className="sw-button" onClick={() => chart.current?.timeScale().fitContent()}>
            Reset view
          </button>
        </div>
      )}
      <div
        ref={container}
        role="img"
        aria-label={`${label} interactive chart${showDataTable ? '. Data table available below.' : ''}`}
        style={{ height }}
      />
      <p className="mt-2 text-right text-xs text-muted-foreground">
        <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
          Charts by TradingView
        </a>
      </p>
      {showDataTable && (
        <details className="mt-4 text-xs text-muted-foreground">
          <summary>Accessible chart data ({bars.length.toLocaleString()} observations)</summary>
          <div className="flex gap-3 items-center mt-3">
            <button
              className="sw-button"
              disabled={tablePage === 0}
              onClick={() => setTablePage(tablePage - 1)}
            >
              Previous observations
            </button>
            <span>
              {tablePage * 100 + 1}–{Math.min((tablePage + 1) * 100, bars.length)} of {bars.length}
            </span>
            <button
              className="sw-button"
              disabled={(tablePage + 1) * 100 >= bars.length}
              onClick={() => setTablePage(tablePage + 1)}
            >
              Next observations
            </button>
          </div>
          <div className="max-h-64 overflow-auto mt-3">
            <table className="w-full">
              <thead>
                <tr>
                  <th>Date (UTC)</th>
                  <th>Open</th>
                  <th>High</th>
                  <th>Low</th>
                  <th>Close</th>
                  <th>Volume</th>
                </tr>
              </thead>
              <tbody>
                {bars.slice(tablePage * 100, (tablePage + 1) * 100).map((b) => (
                  <tr key={b.at}>
                    <td>{b.at}</td>
                    {['open', 'high', 'low', 'close', 'volume'].map((k) => (
                      <td key={k}>{Number(b[k as keyof ChartBar]).toLocaleString()}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  )
}
export function CryptoMarketChart() {
  const [range, setRange] = useState('1M'),
    [dates, setDates] = useState({ start: '', end: '' }),
    [custom, setCustom] = useState({ start: '', end: '' }),
    [style, setStyle] = useState<ChartStyle>('line'),
    [volume, setVolume] = useState(false)
  const cache = useRef(new Map<string, HistoryResponse>())
  const [data, setData] = useState<HistoryResponse>({ bars: [], status: 'loading' }),
    [error, setError] = useState('')
  useEffect(() => {
    if (range === 'custom' && (!custom.start || !custom.end)) return
    let active = true
    const abort = new AbortController()
    const query = new URLSearchParams({ range, ...(range === 'custom' ? custom : {}) }).toString()
    let timer: ReturnType<typeof setTimeout>
    let pending = true
    async function load() {
      try {
        const r = await fetch('/api/crypto/market/history?' + query, { signal: abort.signal })
        const d = await r.json()
        if (!r.ok) throw Error(d.error)
        if (active) {
          pending = d.refreshing || !['ready', 'failed', 'canceled'].includes(d.status)
          if (d.bars?.length) cache.current.set(query, d)
          setData((old) => (d.status === 'ready' ? d : { ...d, bars: old.bars }))
          setError(d.error || '')
        }
      } catch (e) {
        if (active && !abort.signal.aborted)
          setError(e instanceof Error ? e.message : 'Chart unavailable')
      } finally {
        if (active) timer = setTimeout(load, pending ? 2000 : 60000)
      }
    }
    setData(cache.current.get(query) || { status: 'loading', bars: [] })
    setError('')
    void load()
    return () => {
      active = false
      abort.abort()
      clearTimeout(timer)
    }
  }, [range, custom])
  const first = data.bars[0],
    last = data.bars.at(-1),
    change = first && last ? (last.close / first.close - 1) * 100 : null
  return (
    <section className="sw-panel">
      <div className="sw-panel-heading">
        <div>
          <p className="sw-muted">CRYPTO / BTC–USD</p>
          <h2 className="mt-2">Bitcoin</h2>
          <div className="flex items-baseline gap-3 mt-3">
            <strong className="text-3xl font-medium tabular-nums">
              {last
                ? '$' + last.close.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : 'Price unavailable'}
            </strong>
            {change !== null && (
              <span className={change >= 0 ? 'text-gain' : 'text-loss'}>
                {change >= 0 ? '+' : ''}
                {change.toFixed(2)}%{' '}
                <small className="text-muted-foreground">in displayed period</small>
              </span>
            )}
          </div>
        </div>
      </div>
      <ChartControls
        range={range}
        onRange={setRange}
        ranges={['1D', '1W', '1M', '3M', '6M', '1Y', 'ALL']}
        custom={custom}
        onCustom={setCustom}
        style={style}
        onStyle={setStyle}
        volume={volume}
        onVolume={() => setVolume(!volume)}
      />
      {data.gaps || data.partial ? (
        <p className="sw-notice mb-3">
          {data.partial ? 'Partial provider response. ' : ''}
          {data.gaps ? `${data.gaps} gaps in this history. ` : ''}Only supplied prices are plotted;
          displayed-period change may cover less than the requested window.
        </p>
      ) : null}
      {data.stale && (
        <p className="sw-muted mb-3" role="status">
          Showing previously collected history
          {data.refreshing ? ' · Refreshing in the background…' : ' · Refresh unavailable.'}
        </p>
      )}
      {error && (
        <p role="alert" className="sw-notice sw-error mb-4">
          {error}
        </p>
      )}
      {data.bars.length ? (
        <InteractiveChart
          key={range + custom.start + custom.end}
          bars={data.bars}
          style={style}
          volume={volume}
          label="BTC/USD"
          showDataTable={false}
        />
      ) : (
        <div className="sw-empty" style={{ minHeight: 420 }}>
          {data.status === 'ready'
            ? 'No historical prices cover this interval.'
            : data.status === 'failed' || data.status === 'canceled'
              ? 'History collection did not complete. Try another range or check Crypto operations.'
              : 'Collecting this range for the first time… Previously viewed ranges stay cached.'}
        </div>
      )}
    </section>
  )
}
