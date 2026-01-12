'use client'

import { useState, useEffect } from 'react'
import { useSetAtom } from 'jotai'
import { X, DollarSign, TrendingUp } from 'lucide-react'
import { addPaperTradeAtom } from '@/lib/atoms'
import { cn, formatCurrency } from '@/lib/utils'
import type { PaperTrade } from '@/types'

interface CreateTradeModalProps {
  isOpen: boolean
  onClose: () => void
  ticker?: string
  currentPrice?: number
}

const HOLD_PERIODS: { label: string; value: PaperTrade['holdPeriod'] }[] = [
  { label: '1 Week', value: '1_week' },
  { label: '1 Month', value: '1_month' },
  { label: '3 Months', value: '3_months' },
  { label: '6 Months', value: '6_months' },
  { label: '1 Year', value: '1_year' },
]

export function CreateTradeModal({
  isOpen,
  onClose,
  ticker: initialTicker = '',
  currentPrice: initialPrice = 0,
}: CreateTradeModalProps) {
  const addPaperTrade = useSetAtom(addPaperTradeAtom)

  const [tradeType, setTradeType] = useState<'paper' | 'real'>('paper')
  const [ticker, setTicker] = useState(initialTicker)
  const [entryPrice, setEntryPrice] = useState(initialPrice.toString())
  const [investment, setInvestment] = useState('1000')
  const [holdPeriod, setHoldPeriod] = useState<PaperTrade['holdPeriod']>('1_month')
  const [targetPrice, setTargetPrice] = useState('')
  const [notes, setNotes] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Update initial values when props change
  useEffect(() => {
    if (initialTicker) setTicker(initialTicker)
    if (initialPrice > 0) setEntryPrice(initialPrice.toString())
  }, [initialTicker, initialPrice])

  // Calculate shares
  const shares = entryPrice && investment
    ? parseFloat(investment) / parseFloat(entryPrice)
    : 0

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    // Validate
    if (!ticker.trim()) {
      setError('Ticker is required')
      return
    }

    const priceNum = parseFloat(entryPrice)
    const investmentNum = parseFloat(investment)

    if (isNaN(priceNum) || priceNum <= 0) {
      setError('Entry price must be a positive number')
      return
    }

    if (isNaN(investmentNum) || investmentNum <= 0) {
      setError('Investment must be a positive number')
      return
    }

    setIsSubmitting(true)

    try {
      const trade: Omit<PaperTrade, 'id'> = {
        type: tradeType,
        ticker: ticker.toUpperCase(),
        entryDate: new Date().toISOString(),
        entryPrice: priceNum,
        currentPrice: priceNum,
        shares: shares,
        investment: investmentNum,
        profitLoss: 0,
        profitLossPct: 0,
        holdPeriod,
        targetPrice: targetPrice ? parseFloat(targetPrice) : undefined,
        notes: notes.trim() || undefined,
        status: 'active',
      }

      addPaperTrade(trade)
      onClose()

      // Reset form
      setTicker('')
      setEntryPrice('')
      setInvestment('1000')
      setHoldPeriod('1_month')
      setTargetPrice('')
      setNotes('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create trade')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-background/80 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-card border rounded-lg shadow-lg w-full max-w-md mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-semibold">Create Trade</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-muted rounded-md"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Trade Type */}
          <div>
            <label className="text-sm font-medium mb-2 block">Trade Type</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setTradeType('paper')}
                className={cn(
                  'px-4 py-3 rounded-md border-2 transition-colors',
                  tradeType === 'paper'
                    ? 'border-blue-500 bg-blue-500/10 text-blue-600'
                    : 'border-muted hover:border-muted-foreground/50'
                )}
              >
                <TrendingUp className="h-5 w-5 mx-auto mb-1" />
                <span className="text-sm font-medium">Paper Trade</span>
                <p className="text-xs text-muted-foreground mt-1">Practice mode</p>
              </button>
              <button
                type="button"
                onClick={() => setTradeType('real')}
                className={cn(
                  'px-4 py-3 rounded-md border-2 transition-colors',
                  tradeType === 'real'
                    ? 'border-green-500 bg-green-500/10 text-green-600'
                    : 'border-muted hover:border-muted-foreground/50'
                )}
              >
                <DollarSign className="h-5 w-5 mx-auto mb-1" />
                <span className="text-sm font-medium">Real Trade</span>
                <p className="text-xs text-muted-foreground mt-1">Track actual</p>
              </button>
            </div>
          </div>

          {/* Ticker */}
          <div>
            <label htmlFor="ticker" className="text-sm font-medium mb-2 block">
              Ticker Symbol
            </label>
            <input
              id="ticker"
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="AAPL"
              className="w-full px-3 py-2 rounded-md border bg-background"
              required
            />
          </div>

          {/* Entry Price */}
          <div>
            <label htmlFor="entryPrice" className="text-sm font-medium mb-2 block">
              Entry Price
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">
                $
              </span>
              <input
                id="entryPrice"
                type="number"
                step="0.01"
                min="0"
                value={entryPrice}
                onChange={(e) => setEntryPrice(e.target.value)}
                placeholder="0.00"
                className="w-full px-3 py-2 pl-7 rounded-md border bg-background"
                required
              />
            </div>
          </div>

          {/* Investment Amount */}
          <div>
            <label htmlFor="investment" className="text-sm font-medium mb-2 block">
              Investment Amount
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">
                $
              </span>
              <input
                id="investment"
                type="number"
                step="0.01"
                min="0"
                value={investment}
                onChange={(e) => setInvestment(e.target.value)}
                placeholder="1000"
                className="w-full px-3 py-2 pl-7 rounded-md border bg-background"
                required
              />
            </div>
            {shares > 0 && (
              <p className="text-xs text-muted-foreground mt-1">
                ≈ {shares.toFixed(4)} shares
              </p>
            )}
          </div>

          {/* Hold Period */}
          <div>
            <label htmlFor="holdPeriod" className="text-sm font-medium mb-2 block">
              Expected Hold Period
            </label>
            <select
              id="holdPeriod"
              value={holdPeriod}
              onChange={(e) => setHoldPeriod(e.target.value as PaperTrade['holdPeriod'])}
              className="w-full px-3 py-2 rounded-md border bg-background"
            >
              {HOLD_PERIODS.map(({ label, value }) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          {/* Target Price (optional) */}
          <div>
            <label htmlFor="targetPrice" className="text-sm font-medium mb-2 block">
              Target Price <span className="text-muted-foreground">(optional)</span>
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">
                $
              </span>
              <input
                id="targetPrice"
                type="number"
                step="0.01"
                min="0"
                value={targetPrice}
                onChange={(e) => setTargetPrice(e.target.value)}
                placeholder="0.00"
                className="w-full px-3 py-2 pl-7 rounded-md border bg-background"
              />
            </div>
            {targetPrice && entryPrice && (
              <p className="text-xs text-muted-foreground mt-1">
                Target gain: {formatCurrency((parseFloat(targetPrice) - parseFloat(entryPrice)) * shares)} ({(((parseFloat(targetPrice) / parseFloat(entryPrice)) - 1) * 100).toFixed(1)}%)
              </p>
            )}
          </div>

          {/* Notes (optional) */}
          <div>
            <label htmlFor="notes" className="text-sm font-medium mb-2 block">
              Notes <span className="text-muted-foreground">(optional)</span>
            </label>
            <textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Why are you taking this trade?"
              rows={3}
              className="w-full px-3 py-2 rounded-md border bg-background resize-none"
            />
          </div>

          {/* Error */}
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 rounded-md border hover:bg-muted"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className={cn(
                'flex-1 px-4 py-2 rounded-md text-white transition-colors',
                tradeType === 'paper'
                  ? 'bg-blue-500 hover:bg-blue-600'
                  : 'bg-green-500 hover:bg-green-600',
                isSubmitting && 'opacity-50 cursor-not-allowed'
              )}
            >
              {isSubmitting ? 'Creating...' : 'Create Trade'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
