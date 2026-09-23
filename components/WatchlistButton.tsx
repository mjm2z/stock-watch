'use client'
import { Star } from 'lucide-react'
import { useSharedWatchlist } from '@/lib/use-shared-watchlist'
import { cn } from '@/lib/utils'
export function WatchlistButton({ ticker, className, variant = 'default' }: { ticker: string; className?: string; variant?: 'default' | 'icon' }) {
  const { watchlist, ready, busy, error, add, remove } = useSharedWatchlist()
  const included = watchlist.some(item => item.ticker === ticker.toUpperCase())
  return <span>
    <button disabled={!ready || busy} onClick={() => { void (included ? remove(ticker) : add(ticker)) }}
      title={included ? 'Remove from shared watchlist' : 'Add to shared watchlist'}
      className={cn('inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm disabled:opacity-50', included && 'text-primary', className)}>
      <Star className={cn('h-4 w-4', included && 'fill-current')} />
      {variant !== 'icon' && (!ready ? 'Loading watchlist…' : included ? 'Watching' : 'Watch stock')}
    </button>
    {error && <span role="alert" className="mt-1 block text-xs text-destructive">{error}</span>}
  </span>
}
