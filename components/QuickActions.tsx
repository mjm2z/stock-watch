'use client'

import { useState, useEffect } from 'react'
import { TrendingUp } from 'lucide-react'
import { WatchlistButton } from '@/components/WatchlistButton'
import { CreateTradeModal } from '@/components/CreateTradeModal'

interface QuickActionsProps {
  ticker: string
}

export function QuickActions({ ticker }: QuickActionsProps) {
  const [isTradeModalOpen, setIsTradeModalOpen] = useState(false)
  const [currentPrice, setCurrentPrice] = useState(0)

  // Fetch current price for the trade modal
  useEffect(() => {
    const fetchPrice = async () => {
      try {
        const response = await fetch(`/api/stock/${ticker}/quote`)
        if (response.ok) {
          const data = await response.json()
          setCurrentPrice(data.quote?.price || 0)
        }
      } catch (error) {
        console.error('Failed to fetch price:', error)
      }
    }

    fetchPrice()
  }, [ticker])

  return (
    <>
      <div className="rounded-lg border bg-card p-6">
        <h2 className="text-lg font-semibold mb-4">Quick Actions</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <WatchlistButton ticker={ticker} />
          <button
            onClick={() => setIsTradeModalOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-md bg-blue-500 text-white hover:bg-blue-600 transition-colors"
          >
            <TrendingUp className="h-4 w-4" />
            Create Paper Trade
          </button>
        </div>
      </div>

      <CreateTradeModal
        isOpen={isTradeModalOpen}
        onClose={() => setIsTradeModalOpen(false)}
        ticker={ticker}
        currentPrice={currentPrice}
      />
    </>
  )
}
