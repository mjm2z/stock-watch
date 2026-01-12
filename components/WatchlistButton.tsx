'use client'

import { useAtom, useSetAtom } from 'jotai'
import { Star, Check } from 'lucide-react'
import { watchlistAtom, addToWatchlistAtom, removeFromWatchlistAtom } from '@/lib/atoms'
import { cn } from '@/lib/utils'

interface WatchlistButtonProps {
  ticker: string
  className?: string
  variant?: 'default' | 'icon'
}

export function WatchlistButton({
  ticker,
  className,
  variant = 'default',
}: WatchlistButtonProps) {
  const [watchlist] = useAtom(watchlistAtom)
  const addToWatchlist = useSetAtom(addToWatchlistAtom)
  const removeFromWatchlist = useSetAtom(removeFromWatchlistAtom)

  const isInWatchlist = watchlist.some(
    item => item.ticker.toUpperCase() === ticker.toUpperCase()
  )

  const handleClick = () => {
    if (isInWatchlist) {
      removeFromWatchlist(ticker)
    } else {
      addToWatchlist(ticker)
    }
  }

  if (variant === 'icon') {
    return (
      <button
        onClick={handleClick}
        className={cn(
          'p-2 rounded-md transition-colors',
          isInWatchlist
            ? 'bg-primary/10 text-primary'
            : 'hover:bg-muted text-muted-foreground',
          className
        )}
        title={isInWatchlist ? 'Remove from watchlist' : 'Add to watchlist'}
      >
        <Star
          className={cn('h-5 w-5', isInWatchlist && 'fill-current')}
        />
      </button>
    )
  }

  return (
    <button
      onClick={handleClick}
      className={cn(
        'inline-flex items-center gap-2 px-4 py-2 rounded-md transition-colors',
        isInWatchlist
          ? 'bg-primary/10 text-primary border border-primary/20'
          : 'bg-primary text-primary-foreground hover:bg-primary/90',
        className
      )}
    >
      {isInWatchlist ? (
        <>
          <Check className="h-4 w-4" />
          In Watchlist
        </>
      ) : (
        <>
          <Star className="h-4 w-4" />
          Add to Watchlist
        </>
      )}
    </button>
  )
}
