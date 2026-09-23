'use client'
import { useCallback, useEffect, useState } from 'react'
import type { WatchlistItem } from '@/types'

export function useSharedWatchlist() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const refresh = useCallback(async () => {
    try {
      const response = await fetch('/api/research', {
        cache: 'no-store',
        signal: AbortSignal.timeout(10000),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error)
      setWatchlist(data.watchlist)
      setReady(true)
      setError(null)
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not load shared watchlist.')
    }
  }, [])
  useEffect(() => {
    void refresh()
    const listener = () => {
      void refresh()
    }
    window.addEventListener('research-updated', listener)
    window.addEventListener('focus', listener)
    const timer = setInterval(listener, 60000)
    return () => {
      clearInterval(timer)
      window.removeEventListener('research-updated', listener)
      window.removeEventListener('focus', listener)
    }
  }, [refresh])
  const update = async (action: 'watch' | 'unwatch', ticker: string, notes = '') => {
    setBusy(true)
    try {
      const response = await fetch('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ticker, notes }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error)
      await refresh()
      window.dispatchEvent(new Event('research-updated'))
      return true
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not update watchlist.')
      return false
    } finally {
      setBusy(false)
    }
  }
  return {
    watchlist,
    ready,
    busy,
    error,
    refresh,
    add: (ticker: string, notes?: string) => update('watch', ticker, notes),
    remove: (ticker: string) => update('unwatch', ticker),
  }
}
