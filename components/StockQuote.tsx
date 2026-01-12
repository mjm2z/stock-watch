'use client'

import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown, Loader2, RefreshCw } from 'lucide-react'
import { cn, formatCurrency, formatPercent, formatLargeNumber } from '@/lib/utils'
import type { Quote, Fundamentals } from '@/types'

interface StockQuoteProps {
  ticker: string
  className?: string
}

interface QuoteResponse {
  quote: Quote
  fundamentals: Fundamentals | null
  meta: {
    ticker: string
    provider: string
    timestamp: string
  }
}

export function StockQuote({ ticker, className }: StockQuoteProps) {
  const [data, setData] = useState<QuoteResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const fetchQuote = async (refresh = false) => {
    if (refresh) {
      setIsRefreshing(true)
    } else {
      setIsLoading(true)
    }
    setError(null)

    try {
      const response = await fetch(`/api/stock/${ticker}/quote`)

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'Failed to fetch quote')
      }

      const result: QuoteResponse = await response.json()
      setData(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load quote')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }

  useEffect(() => {
    fetchQuote()
  }, [ticker]) // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) {
    return (
      <div className={cn('rounded-lg border bg-card p-6', className)}>
        <div className="flex items-center justify-center h-32">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={cn('rounded-lg border bg-card p-6', className)}>
        <div className="text-center">
          <p className="text-destructive mb-2">{error}</p>
          <button
            onClick={() => fetchQuote()}
            className="text-sm text-primary hover:underline"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  if (!data) return null

  const { quote, fundamentals } = data
  const isPositive = quote.changePercent >= 0

  return (
    <div className={cn('rounded-lg border bg-card', className)}>
      {/* Header with price */}
      <div className="p-6 border-b">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold">{ticker}</h1>
              {fundamentals?.name && (
                <span className="text-muted-foreground">
                  {fundamentals.name}
                </span>
              )}
            </div>
            {fundamentals?.sector && (
              <p className="text-sm text-muted-foreground mt-1">
                {fundamentals.sector}
              </p>
            )}
          </div>
          <button
            onClick={() => fetchQuote(true)}
            disabled={isRefreshing}
            className="p-2 hover:bg-muted rounded-md transition-colors"
            title="Refresh quote"
          >
            <RefreshCw
              className={cn('h-4 w-4', isRefreshing && 'animate-spin')}
            />
          </button>
        </div>

        <div className="mt-4 flex items-baseline gap-3">
          <span className="text-4xl font-bold">
            {formatCurrency(quote.price)}
          </span>
          <div
            className={cn(
              'flex items-center gap-1 text-lg font-medium',
              isPositive ? 'text-gain' : 'text-loss'
            )}
          >
            {isPositive ? (
              <TrendingUp className="h-5 w-5" />
            ) : (
              <TrendingDown className="h-5 w-5" />
            )}
            <span>
              {isPositive ? '+' : ''}
              {formatCurrency(quote.change)}
            </span>
            <span>
              ({isPositive ? '+' : ''}
              {formatPercent(quote.changePercent)})
            </span>
          </div>
        </div>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-6">
        <MetricItem label="Open" value={formatCurrency(quote.open)} />
        <MetricItem label="High" value={formatCurrency(quote.high)} />
        <MetricItem label="Low" value={formatCurrency(quote.low)} />
        <MetricItem label="Prev Close" value={formatCurrency(quote.previousClose)} />

        {fundamentals && (
          <>
            <MetricItem
              label="Market Cap"
              value={formatLargeNumber(fundamentals.marketCap)}
            />
            {fundamentals.pe && (
              <MetricItem label="P/E Ratio" value={fundamentals.pe.toFixed(2)} />
            )}
            {fundamentals.eps && (
              <MetricItem label="EPS" value={formatCurrency(fundamentals.eps)} />
            )}
            {fundamentals.dividendYield && (
              <MetricItem
                label="Dividend Yield"
                value={formatPercent(fundamentals.dividendYield)}
              />
            )}
            {fundamentals.fiftyTwoWeekHigh > 0 && (
              <MetricItem
                label="52W High"
                value={formatCurrency(fundamentals.fiftyTwoWeekHigh)}
              />
            )}
            {fundamentals.fiftyTwoWeekLow > 0 && (
              <MetricItem
                label="52W Low"
                value={formatCurrency(fundamentals.fiftyTwoWeekLow)}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}

function MetricItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium">{value}</p>
    </div>
  )
}
