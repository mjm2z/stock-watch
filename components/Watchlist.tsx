'use client'

import { useState, useEffect, useCallback } from 'react'
import { useAtom, useSetAtom } from 'jotai'
import Link from 'next/link'
import {
  RefreshCw,
  Trash2,
  TrendingUp,
  TrendingDown,
  ArrowUpDown,
  ChevronUp,
  ChevronDown,
  Eye,
  ListPlus,
} from 'lucide-react'
import { watchlistAtom, removeFromWatchlistAtom } from '@/lib/atoms'
import { cn, formatCurrency, formatPercent } from '@/lib/utils'
import type { WatchlistItem } from '@/types'

type SortField = 'ticker' | 'price' | 'change' | 'addedAt'
type SortDirection = 'asc' | 'desc'

interface WatchlistPrice {
  price: number
  change: number
  changePercent: number
}

interface WatchlistItemWithPrice extends WatchlistItem {
  currentPrice?: number
  priceChange?: number
  priceChangePercent?: number
}

export function Watchlist() {
  const [watchlist] = useAtom(watchlistAtom)
  const removeFromWatchlist = useSetAtom(removeFromWatchlistAtom)

  const [prices, setPrices] = useState<Record<string, WatchlistPrice>>({})
  const [isLoading, setIsLoading] = useState(false)
  const [sortField, setSortField] = useState<SortField>('addedAt')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [itemToDelete, setItemToDelete] = useState<string | null>(null)

  // Fetch prices for all watchlist items
  const fetchPrices = useCallback(async () => {
    if (watchlist.length === 0) return

    setIsLoading(true)
    try {
      const response = await fetch('/api/watchlist/prices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers: watchlist.map(w => w.ticker) }),
      })

      if (response.ok) {
        const data = await response.json()
        setPrices(data.prices)
      }
    } catch (error) {
      console.error('Failed to fetch watchlist prices:', error)
    } finally {
      setIsLoading(false)
    }
  }, [watchlist])

  // Fetch prices on mount and when watchlist changes
  useEffect(() => {
    fetchPrices()
  }, [fetchPrices])

  // Combine watchlist with prices
  const itemsWithPrices: WatchlistItemWithPrice[] = watchlist.map(item => ({
    ...item,
    currentPrice: prices[item.ticker]?.price,
    priceChange: prices[item.ticker]?.change,
    priceChangePercent: prices[item.ticker]?.changePercent,
  }))

  // Sort items
  const sortedItems = [...itemsWithPrices].sort((a, b) => {
    let comparison = 0

    switch (sortField) {
      case 'ticker':
        comparison = a.ticker.localeCompare(b.ticker)
        break
      case 'price':
        comparison = (a.currentPrice || 0) - (b.currentPrice || 0)
        break
      case 'change':
        comparison = (a.priceChangePercent || 0) - (b.priceChangePercent || 0)
        break
      case 'addedAt':
        comparison = new Date(a.addedAt).getTime() - new Date(b.addedAt).getTime()
        break
    }

    return sortDirection === 'asc' ? comparison : -comparison
  })

  // Handle sort click
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('desc')
    }
  }

  // Handle delete confirmation
  const handleDelete = (ticker: string) => {
    if (itemToDelete === ticker) {
      removeFromWatchlist(ticker)
      setItemToDelete(null)
    } else {
      setItemToDelete(ticker)
      // Reset after 3 seconds
      setTimeout(() => setItemToDelete(null), 3000)
    }
  }

  // Sort indicator component
  const SortIndicator = ({ field }: { field: SortField }) => {
    if (sortField !== field) {
      return <ArrowUpDown className="h-4 w-4 text-muted-foreground/50" />
    }
    return sortDirection === 'asc' ? (
      <ChevronUp className="h-4 w-4" />
    ) : (
      <ChevronDown className="h-4 w-4" />
    )
  }

  // Empty state
  if (watchlist.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-8 text-center">
        <ListPlus className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
        <h3 className="text-lg font-semibold mb-2">Your watchlist is empty</h3>
        <p className="text-muted-foreground mb-4">
          Add stocks to your watchlist to track them here.
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
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div>
          <h2 className="font-semibold">Watchlist</h2>
          <p className="text-sm text-muted-foreground">
            Tracking {watchlist.length} stock{watchlist.length !== 1 ? 's' : ''}
          </p>
        </div>
        <button
          onClick={fetchPrices}
          disabled={isLoading}
          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-md hover:bg-muted"
        >
          <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="text-left p-3">
                <button
                  onClick={() => handleSort('ticker')}
                  className="inline-flex items-center gap-1 font-medium text-sm hover:text-foreground"
                >
                  Ticker
                  <SortIndicator field="ticker" />
                </button>
              </th>
              <th className="text-right p-3">
                <button
                  onClick={() => handleSort('price')}
                  className="inline-flex items-center gap-1 font-medium text-sm hover:text-foreground"
                >
                  Price
                  <SortIndicator field="price" />
                </button>
              </th>
              <th className="text-right p-3">
                <button
                  onClick={() => handleSort('change')}
                  className="inline-flex items-center gap-1 font-medium text-sm hover:text-foreground"
                >
                  Change
                  <SortIndicator field="change" />
                </button>
              </th>
              <th className="text-right p-3 hidden sm:table-cell">
                <button
                  onClick={() => handleSort('addedAt')}
                  className="inline-flex items-center gap-1 font-medium text-sm hover:text-foreground"
                >
                  Added
                  <SortIndicator field="addedAt" />
                </button>
              </th>
              <th className="text-right p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sortedItems.map(item => {
              const isPositive = (item.priceChangePercent || 0) >= 0

              return (
                <tr
                  key={item.ticker}
                  className="border-b last:border-0 hover:bg-muted/50 transition-colors"
                >
                  <td className="p-3">
                    <Link
                      href={`/stock/${item.ticker}`}
                      className="font-semibold hover:text-primary"
                    >
                      {item.ticker}
                    </Link>
                    {item.notes && (
                      <p className="text-xs text-muted-foreground truncate max-w-[150px]">
                        {item.notes}
                      </p>
                    )}
                  </td>
                  <td className="p-3 text-right font-medium">
                    {item.currentPrice ? (
                      formatCurrency(item.currentPrice)
                    ) : (
                      <span className="text-muted-foreground">--</span>
                    )}
                  </td>
                  <td className="p-3 text-right">
                    {item.priceChangePercent !== undefined ? (
                      <div
                        className={cn(
                          'inline-flex items-center gap-1',
                          isPositive ? 'text-gain' : 'text-loss'
                        )}
                      >
                        {isPositive ? (
                          <TrendingUp className="h-4 w-4" />
                        ) : (
                          <TrendingDown className="h-4 w-4" />
                        )}
                        <span className="font-medium">
                          {formatPercent(item.priceChangePercent)}
                        </span>
                      </div>
                    ) : (
                      <span className="text-muted-foreground">--</span>
                    )}
                  </td>
                  <td className="p-3 text-right text-sm text-muted-foreground hidden sm:table-cell">
                    {new Date(item.addedAt).toLocaleDateString()}
                  </td>
                  <td className="p-3 text-right">
                    <div className="inline-flex items-center gap-1">
                      <Link
                        href={`/stock/${item.ticker}`}
                        className="p-2 hover:bg-muted rounded-md"
                        title="View stock"
                      >
                        <Eye className="h-4 w-4" />
                      </Link>
                      <button
                        onClick={() => handleDelete(item.ticker)}
                        className={cn(
                          'p-2 rounded-md transition-colors',
                          itemToDelete === item.ticker
                            ? 'bg-destructive text-destructive-foreground'
                            : 'hover:bg-muted text-muted-foreground hover:text-destructive'
                        )}
                        title={itemToDelete === item.ticker ? 'Click again to confirm' : 'Remove from watchlist'}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pro tip */}
      <div className="p-4 border-t bg-muted/30 text-sm text-muted-foreground">
        <strong>Pro tip:</strong> Start with 10-20 stocks. Master these before expanding.
      </div>
    </div>
  )
}
