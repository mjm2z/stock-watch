'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import {
  createChart,
  ColorType,
  CrosshairMode,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  LineData,
  HistogramData,
  Time,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
} from 'lightweight-charts'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PriceData } from '@/types'

type TimeRange = '1D' | '1W' | '1M' | '3M' | '1Y' | '5Y'

interface StockChartProps {
  ticker: string
  className?: string
}

interface ChartData {
  candles: CandlestickData<Time>[]
  volume: HistogramData<Time>[]
  ma50: LineData<Time>[]
  ma200: LineData<Time>[]
}

const TIME_RANGES: { label: string; value: TimeRange }[] = [
  { label: '1D', value: '1D' },
  { label: '1W', value: '1W' },
  { label: '1M', value: '1M' },
  { label: '3M', value: '3M' },
  { label: '1Y', value: '1Y' },
  { label: '5Y', value: '5Y' },
]

/**
 * Calculate Simple Moving Average
 */
function chartTime(value: string, intraday: boolean): Time {
  return intraday ? (Math.floor(Date.parse(value) / 1000) as Time) : (value.split('T')[0] as Time)
}

function calculateSMA(data: PriceData[], period: number): LineData<Time>[] {
  const result: LineData<Time>[] = []

  for (let i = period - 1; i < data.length; i++) {
    let sum = 0
    for (let j = 0; j < period; j++) {
      sum += data[i - j].close
    }
    result.push({
      time: data[i].date.split('T')[0] as Time,
      value: sum / period,
    })
  }

  return result
}

/**
 * Transform API data to chart format
 */
function transformData(prices: PriceData[], intraday = false): ChartData {
  const candles: CandlestickData<Time>[] = []
  const volume: HistogramData<Time>[] = []

  for (const price of prices) {
    const time = chartTime(price.date, intraday)

    candles.push({
      time,
      open: price.open,
      high: price.high,
      low: price.low,
      close: price.close,
    })

    volume.push({
      time,
      value: price.volume,
      color: price.close >= price.open ? 'rgba(38, 166, 154, 0.5)' : 'rgba(239, 83, 80, 0.5)',
    })
  }

  // Calculate moving averages (only meaningful for longer timeframes)
  const ma50 = !intraday && prices.length >= 50 ? calculateSMA(prices, 50) : []
  const ma200 = !intraday && prices.length >= 200 ? calculateSMA(prices, 200) : []

  return { candles, volume, ma50, ma200 }
}

export function StockChart({ ticker, className }: StockChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const ma50SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const ma200SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  const requestId = useRef(0)
  const [loadedRange, setLoadedRange] = useState<TimeRange | null>(null)
  const [overlays, setOverlays] = useState({ ma50: false, ma200: false })
  const [empty, setEmpty] = useState(false)
  const [selectedRange, setSelectedRange] = useState<TimeRange>('1M')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Fetch data for the chart
  const fetchData = useCallback(
    async (range: TimeRange, refresh = false) => {
      const id = ++requestId.current
      if (!refresh) setIsLoading(true)
      setError(null)

      try {
        const response = await fetch(`/api/stock/${ticker}/history?range=${range}`, {
          signal: AbortSignal.timeout(15000),
        })

        if (!response.ok) {
          const errorData = await response.json()
          throw new Error(errorData.error || 'Failed to fetch chart data')
        }

        const result = await response.json()
        if (id !== requestId.current) return
        const chartData = transformData(result.data, range === '1D' || range === '1W')

        setLoadedRange(range)
        setEmpty(!chartData.candles.length)
        setOverlays({ ma50: !!chartData.ma50.length, ma200: !!chartData.ma200.length })
        // Update chart series
        if (candlestickSeriesRef.current) {
          candlestickSeriesRef.current.setData(chartData.candles)
        }
        if (volumeSeriesRef.current) {
          volumeSeriesRef.current.setData(chartData.volume)
        }
        if (ma50SeriesRef.current) {
          ma50SeriesRef.current.setData(chartData.ma50)
        }
        if (ma200SeriesRef.current) {
          ma200SeriesRef.current.setData(chartData.ma200)
        }

        // Fit content to view
        if (chartRef.current && !refresh) {
          chartRef.current.timeScale().fitContent()
        }
      } catch (err) {
        if (id !== requestId.current) return
        setError(err instanceof Error ? err.message : 'Failed to load chart')
      } finally {
        if (id === requestId.current) setIsLoading(false)
      }
    },
    [ticker]
  )

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return

    // Detect dark mode
    const isDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches

    const requests = requestId
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDarkMode ? '#d1d5db' : '#374151',
      },
      grid: {
        vertLines: { color: isDarkMode ? '#374151' : '#e5e7eb' },
        horzLines: { color: isDarkMode ? '#374151' : '#e5e7eb' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: isDarkMode ? '#374151' : '#e5e7eb',
      },
      timeScale: {
        borderColor: isDarkMode ? '#374151' : '#e5e7eb',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: {
        vertTouchDrag: false,
      },
    })

    chartRef.current = chart

    // Candlestick series (v5 API)
    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderDownColor: '#ef5350',
      borderUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      wickUpColor: '#26a69a',
    })
    candlestickSeriesRef.current = candlestickSeries

    // Volume series (v5 API)
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    })
    volumeSeriesRef.current = volumeSeries

    // 50-day MA (v5 API)
    const ma50Series = chart.addSeries(LineSeries, {
      color: '#2962FF',
      lineWidth: 1,
      title: 'MA50',
    })
    ma50SeriesRef.current = ma50Series

    // 200-day MA (v5 API)
    const ma200Series = chart.addSeries(LineSeries, {
      color: '#FF6D00',
      lineWidth: 1,
      title: 'MA200',
    })
    ma200SeriesRef.current = ma200Series

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
        })
      }
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      requests.current++
      chart.remove()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Refetch when range changes
  useEffect(() => {
    const requests = requestId
    if (chartRef.current) {
      fetchData(selectedRange)
    }
    const timer = setInterval(() => {
      if (!document.hidden) void fetchData(selectedRange, true)
    }, 60000)
    return () => {
      requests.current++
      clearInterval(timer)
    }
  }, [selectedRange, fetchData])

  const handleRangeChange = (range: TimeRange) => {
    requestId.current++
    setSelectedRange(range)
  }

  return (
    <div className={cn('rounded-lg border bg-card', className)}>
      {/* Timeframe selector */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3">
        <h3 className="font-semibold">Price Chart</h3>
        <div className="flex gap-1">
          {TIME_RANGES.map(({ label, value }) => (
            <button
              key={value}
              aria-pressed={selectedRange === value}
              onClick={() => handleRangeChange(value)}
              className={cn(
                'min-h-11 px-3 py-1 text-sm rounded-md transition-colors',
                selectedRange === value ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart container */}
      <div className="relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/50 z-10">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && (
          <div role="alert" className="p-3 text-sm text-amber-700">
            Chart could not refresh.{loadedRange ? ` Showing the last ${loadedRange} data.` : ''}{' '}
            <button className="min-h-11 underline" onClick={() => fetchData(selectedRange)}>
              Retry
            </button>
          </div>
        )}
        {empty && !error && (
          <p className="p-3 text-sm">No price bars are available for this period.</p>
        )}

        <div ref={chartContainerRef} className="h-[400px] w-full" />
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 px-3 pb-3 text-xs text-muted-foreground">
        {overlays.ma50 && (
          <div className="flex items-center gap-1">
            <div className="h-2 w-4 rounded" style={{ backgroundColor: '#2962FF' }} />
            <span>50-day MA</span>
          </div>
        )}
        {overlays.ma200 && (
          <div className="flex items-center gap-1">
            <div className="h-2 w-4 rounded" style={{ backgroundColor: '#FF6D00' }} />
            <span>200-day MA</span>
          </div>
        )}
      </div>
    </div>
  )
}
