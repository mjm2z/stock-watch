'use client'

import { useState, useEffect, useCallback } from 'react'
import { useAtom, useSetAtom } from 'jotai'
import Link from 'next/link'
import {
  TrendingUp,
  TrendingDown,
  RefreshCw,
  X,
  ChevronDown,
  ChevronUp,
  MoreHorizontal,
} from 'lucide-react'
import {
  paperTradesAtom,
  updatePaperTradeAtom,
  closePaperTradeAtom,
} from '@/lib/atoms'
import { cn, formatCurrency, formatPercent } from '@/lib/utils'
import type { PaperTrade } from '@/types'

type FilterType = 'all' | 'paper' | 'real'
type StatusFilter = 'all' | 'active' | 'closed'

function daysBetween(date1: string, date2: string = new Date().toISOString()): number {
  const d1 = new Date(date1)
  const d2 = new Date(date2)
  return Math.floor((d2.getTime() - d1.getTime()) / (1000 * 60 * 60 * 24))
}

export function TradeTable() {
  const [trades] = useAtom(paperTradesAtom)
  const updateTrade = useSetAtom(updatePaperTradeAtom)
  const closeTrade = useSetAtom(closePaperTradeAtom)

  const [typeFilter, setTypeFilter] = useState<FilterType>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active')
  const [isUpdatingPrices, setIsUpdatingPrices] = useState(false)
  const [expandedTrade, setExpandedTrade] = useState<string | null>(null)
  const [tradeToClose, setTradeToClose] = useState<string | null>(null)

  // Filter trades
  const filteredTrades = trades.filter(trade => {
    if (typeFilter !== 'all' && trade.type !== typeFilter) return false
    if (statusFilter !== 'all' && trade.status !== statusFilter) return false
    return true
  })

  // Update prices for active trades
  const updatePrices = useCallback(async () => {
    const activeTrades = trades.filter(t => t.status === 'active')
    if (activeTrades.length === 0) return

    setIsUpdatingPrices(true)
    try {
      const response = await fetch('/api/watchlist/prices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers: activeTrades.map(t => t.ticker) }),
      })

      if (response.ok) {
        const data = await response.json()
        const prices = data.prices as Record<string, { price: number }>

        // Update each trade with new price
        for (const trade of activeTrades) {
          const newPrice = prices[trade.ticker]?.price
          if (newPrice && newPrice !== trade.currentPrice) {
            const profitLoss = (newPrice - trade.entryPrice) * trade.shares
            const profitLossPct = ((newPrice - trade.entryPrice) / trade.entryPrice) * 100

            updateTrade(trade.id, {
              currentPrice: newPrice,
              profitLoss,
              profitLossPct,
            })
          }
        }
      }
    } catch (error) {
      console.error('Failed to update prices:', error)
    } finally {
      setIsUpdatingPrices(false)
    }
  }, [trades, updateTrade])

  // Update prices on mount
  useEffect(() => {
    updatePrices()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Handle close trade
  const handleCloseTrade = async (tradeId: string) => {
    const trade = trades.find(t => t.id === tradeId)
    if (!trade) return

    // Use current price to close
    closeTrade(tradeId, trade.currentPrice)
    setTradeToClose(null)
  }

  // Empty state
  if (trades.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-8 text-center">
        <TrendingUp className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
        <h3 className="text-lg font-semibold mb-2">No trades yet</h3>
        <p className="text-muted-foreground mb-4">
          Create your first paper trade to start tracking your performance.
        </p>
        <Link
          href="/"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
        >
          Search for stocks
        </Link>
      </div>
    )
  }

  return (
    <div className="rounded-lg border bg-card">
      {/* Header with filters */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 border-b">
        <div className="flex items-center gap-2">
          {/* Type filter */}
          <div className="flex rounded-md border">
            {(['all', 'paper', 'real'] as FilterType[]).map(type => (
              <button
                key={type}
                onClick={() => setTypeFilter(type)}
                className={cn(
                  'px-3 py-1.5 text-sm capitalize',
                  typeFilter === type
                    ? 'bg-primary text-primary-foreground'
                    : 'hover:bg-muted'
                )}
              >
                {type}
              </button>
            ))}
          </div>

          {/* Status filter */}
          <div className="flex rounded-md border">
            {(['all', 'active', 'closed'] as StatusFilter[]).map(status => (
              <button
                key={status}
                onClick={() => setStatusFilter(status)}
                className={cn(
                  'px-3 py-1.5 text-sm capitalize',
                  statusFilter === status
                    ? 'bg-primary text-primary-foreground'
                    : 'hover:bg-muted'
                )}
              >
                {status}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={updatePrices}
          disabled={isUpdatingPrices}
          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-md hover:bg-muted"
        >
          <RefreshCw className={cn('h-4 w-4', isUpdatingPrices && 'animate-spin')} />
          Update Prices
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b bg-muted/50 text-sm">
              <th className="text-left p-3 font-medium">Ticker</th>
              <th className="text-right p-3 font-medium">Entry</th>
              <th className="text-right p-3 font-medium">Current</th>
              <th className="text-right p-3 font-medium">P&L</th>
              <th className="text-right p-3 font-medium hidden sm:table-cell">Days</th>
              <th className="text-center p-3 font-medium">Type</th>
              <th className="text-right p-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredTrades.map(trade => {
              const isPositive = trade.profitLoss >= 0
              const isExpanded = expandedTrade === trade.id

              return (
                <>
                  <tr
                    key={trade.id}
                    className={cn(
                      'border-b hover:bg-muted/50 transition-colors',
                      trade.status === 'closed' && 'opacity-60'
                    )}
                  >
                    <td className="p-3">
                      <Link
                        href={`/stock/${trade.ticker}`}
                        className="font-semibold hover:text-primary"
                      >
                        {trade.ticker}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        {trade.shares.toFixed(2)} shares
                      </p>
                    </td>
                    <td className="p-3 text-right">
                      {formatCurrency(trade.entryPrice)}
                    </td>
                    <td className="p-3 text-right font-medium">
                      {formatCurrency(trade.currentPrice)}
                    </td>
                    <td className="p-3 text-right">
                      <div className={cn(
                        'inline-flex items-center gap-1',
                        isPositive ? 'text-gain' : 'text-loss'
                      )}>
                        {isPositive ? (
                          <TrendingUp className="h-4 w-4" />
                        ) : (
                          <TrendingDown className="h-4 w-4" />
                        )}
                        <div>
                          <div className="font-medium">
                            {isPositive ? '+' : ''}{formatCurrency(trade.profitLoss)}
                          </div>
                          <div className="text-xs">
                            ({isPositive ? '+' : ''}{formatPercent(trade.profitLossPct)})
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="p-3 text-right text-sm text-muted-foreground hidden sm:table-cell">
                      {daysBetween(trade.entryDate)}d
                    </td>
                    <td className="p-3 text-center">
                      <span className={cn(
                        'inline-block px-2 py-0.5 rounded-full text-xs font-medium',
                        trade.type === 'paper'
                          ? 'bg-blue-500/10 text-blue-600'
                          : 'bg-green-500/10 text-green-600'
                      )}>
                        {trade.type}
                      </span>
                    </td>
                    <td className="p-3 text-right">
                      <div className="inline-flex items-center gap-1">
                        <button
                          onClick={() => setExpandedTrade(isExpanded ? null : trade.id)}
                          className="p-2 hover:bg-muted rounded-md"
                        >
                          {isExpanded ? (
                            <ChevronUp className="h-4 w-4" />
                          ) : (
                            <ChevronDown className="h-4 w-4" />
                          )}
                        </button>
                        {trade.status === 'active' && (
                          <button
                            onClick={() => setTradeToClose(
                              tradeToClose === trade.id ? null : trade.id
                            )}
                            className={cn(
                              'p-2 rounded-md transition-colors',
                              tradeToClose === trade.id
                                ? 'bg-destructive text-destructive-foreground'
                                : 'hover:bg-muted'
                            )}
                            title={tradeToClose === trade.id ? 'Click again to confirm' : 'Close trade'}
                          >
                            <X className="h-4 w-4" />
                          </button>
                        )}
                        {tradeToClose === trade.id && (
                          <button
                            onClick={() => handleCloseTrade(trade.id)}
                            className="px-2 py-1 text-xs bg-destructive text-destructive-foreground rounded"
                          >
                            Confirm
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr key={`${trade.id}-expanded`} className="border-b bg-muted/30">
                      <td colSpan={7} className="p-4">
                        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 text-sm">
                          <div>
                            <p className="text-muted-foreground">Entry Date</p>
                            <p className="font-medium">
                              {new Date(trade.entryDate).toLocaleDateString()}
                            </p>
                          </div>
                          <div>
                            <p className="text-muted-foreground">Investment</p>
                            <p className="font-medium">{formatCurrency(trade.investment)}</p>
                          </div>
                          <div>
                            <p className="text-muted-foreground">Hold Period</p>
                            <p className="font-medium">{trade.holdPeriod.replace('_', ' ')}</p>
                          </div>
                          {trade.targetPrice && (
                            <div>
                              <p className="text-muted-foreground">Target Price</p>
                              <p className="font-medium">{formatCurrency(trade.targetPrice)}</p>
                            </div>
                          )}
                          {trade.notes && (
                            <div className="sm:col-span-2 lg:col-span-4">
                              <p className="text-muted-foreground">Notes</p>
                              <p>{trade.notes}</p>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
          </tbody>
        </table>
      </div>

      {filteredTrades.length === 0 && (
        <div className="p-8 text-center text-muted-foreground">
          No trades match the current filters.
        </div>
      )}
    </div>
  )
}
