'use client'

import { atom } from 'jotai'
import { atomWithStorage } from 'jotai/utils'
import type {
  WatchlistItem,
  PaperTrade,
  ApiCosts,
  PortfolioMetrics,
} from '@/types'

/**
 * Watchlist atom - persisted to localStorage
 * Stores user's tracked stocks
 */
export const watchlistAtom = atomWithStorage<WatchlistItem[]>('stock-watch-watchlist', [])

/**
 * Paper trades atom - persisted to localStorage
 * Stores all paper and real trades
 */
export const paperTradesAtom = atomWithStorage<PaperTrade[]>('stock-watch-trades', [])

/**
 * API costs atom - persisted to localStorage
 * Tracks monthly API spending
 */
export const apiCostsAtom = atomWithStorage<ApiCosts>('stock-watch-api-costs', {
  currentMonth: new Date().toISOString().slice(0, 7), // "2024-01"
  claudeCosts: 0,
  fmpCalls: 0,
  analyses: 0,
  budget: 30, // Default $30/month budget
  history: [],
})

/**
 * Derived atom: Active trades only
 */
export const activeTradesAtom = atom((get) => {
  const trades = get(paperTradesAtom)
  return trades.filter((trade) => trade.status === 'active')
})

/**
 * Derived atom: Paper trades only
 */
export const paperOnlyTradesAtom = atom((get) => {
  const trades = get(paperTradesAtom)
  return trades.filter((trade) => trade.type === 'paper')
})

/**
 * Derived atom: Real trades only
 */
export const realOnlyTradesAtom = atom((get) => {
  const trades = get(paperTradesAtom)
  return trades.filter((trade) => trade.type === 'real')
})

/**
 * Derived atom: Total portfolio value (active trades)
 */
export const portfolioValueAtom = atom((get) => {
  const activeTrades = get(activeTradesAtom)
  return activeTrades.reduce(
    (sum, trade) => sum + trade.currentPrice * trade.shares,
    0
  )
})

/**
 * Derived atom: Total invested amount (active trades)
 */
export const totalInvestedAtom = atom((get) => {
  const activeTrades = get(activeTradesAtom)
  return activeTrades.reduce((sum, trade) => sum + trade.investment, 0)
})

/**
 * Derived atom: Total profit/loss
 */
export const totalProfitLossAtom = atom((get) => {
  const portfolioValue = get(portfolioValueAtom)
  const totalInvested = get(totalInvestedAtom)
  return portfolioValue - totalInvested
})

/**
 * Derived atom: Portfolio metrics
 */
export const portfolioMetricsAtom = atom<PortfolioMetrics>((get) => {
  const trades = get(paperTradesAtom)
  const activeTrades = get(activeTradesAtom)
  const portfolioValue = get(portfolioValueAtom)
  const totalInvested = get(totalInvestedAtom)

  // Calculate win rate from closed trades
  const closedTrades = trades.filter((t) => t.status === 'closed')
  const winners = closedTrades.filter((t) => t.profitLoss > 0)
  const losers = closedTrades.filter((t) => t.profitLoss < 0)

  const winRate = closedTrades.length > 0
    ? (winners.length / closedTrades.length) * 100
    : 0

  const avgGain = winners.length > 0
    ? winners.reduce((sum, t) => sum + t.profitLossPct, 0) / winners.length
    : 0

  const avgLoss = losers.length > 0
    ? losers.reduce((sum, t) => sum + t.profitLossPct, 0) / losers.length
    : 0

  const totalProfitLoss = portfolioValue - totalInvested
  const totalProfitLossPct = totalInvested > 0
    ? (totalProfitLoss / totalInvested) * 100
    : 0

  return {
    totalTrades: trades.length,
    activeTrades: activeTrades.length,
    winRate,
    avgGain,
    avgLoss,
    totalInvested,
    currentValue: portfolioValue,
    totalProfitLoss,
    totalProfitLossPct,
  }
})

/**
 * Derived atom: Watchlist tickers (for batch fetching)
 */
export const watchlistTickersAtom = atom((get) => {
  const watchlist = get(watchlistAtom)
  return watchlist.map((item) => item.ticker)
})

/**
 * Helper atom: Check if a ticker is in watchlist
 */
export const isInWatchlistAtom = atom((get) => {
  const watchlist = get(watchlistAtom)
  return (ticker: string) =>
    watchlist.some((item) => item.ticker.toUpperCase() === ticker.toUpperCase())
})

/**
 * Write atom: Add to watchlist
 */
export const addToWatchlistAtom = atom(
  null,
  (get, set, ticker: string, notes?: string) => {
    const watchlist = get(watchlistAtom)
    const exists = watchlist.some(
      (item) => item.ticker.toUpperCase() === ticker.toUpperCase()
    )

    if (!exists) {
      set(watchlistAtom, [
        ...watchlist,
        {
          ticker: ticker.toUpperCase(),
          addedAt: new Date().toISOString(),
          notes,
        },
      ])
    }
  }
)

/**
 * Write atom: Remove from watchlist
 */
export const removeFromWatchlistAtom = atom(
  null,
  (get, set, ticker: string) => {
    const watchlist = get(watchlistAtom)
    set(
      watchlistAtom,
      watchlist.filter(
        (item) => item.ticker.toUpperCase() !== ticker.toUpperCase()
      )
    )
  }
)

/**
 * Write atom: Add paper trade
 */
export const addPaperTradeAtom = atom(
  null,
  (get, set, trade: Omit<PaperTrade, 'id'>) => {
    const trades = get(paperTradesAtom)
    const newTrade: PaperTrade = {
      ...trade,
      id: crypto.randomUUID(),
    }
    set(paperTradesAtom, [...trades, newTrade])
    return newTrade.id
  }
)

/**
 * Write atom: Update paper trade
 */
export const updatePaperTradeAtom = atom(
  null,
  (get, set, id: string, updates: Partial<PaperTrade>) => {
    const trades = get(paperTradesAtom)
    set(
      paperTradesAtom,
      trades.map((trade) =>
        trade.id === id ? { ...trade, ...updates } : trade
      )
    )
  }
)

/**
 * Write atom: Close paper trade
 */
export const closePaperTradeAtom = atom(
  null,
  (get, set, id: string, closedPrice: number) => {
    const trades = get(paperTradesAtom)
    set(
      paperTradesAtom,
      trades.map((trade) => {
        if (trade.id === id) {
          const profitLoss = (closedPrice - trade.entryPrice) * trade.shares
          const profitLossPct = ((closedPrice - trade.entryPrice) / trade.entryPrice) * 100
          return {
            ...trade,
            status: 'closed' as const,
            closedDate: new Date().toISOString(),
            closedPrice,
            currentPrice: closedPrice,
            profitLoss,
            profitLossPct,
          }
        }
        return trade
      })
    )
  }
)
