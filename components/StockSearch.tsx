'use client'

import { useState, useEffect, useRef, useCallback, useId } from 'react'
import { useRouter } from 'next/navigation'
import { Search, AlertCircle, TrendingUp, TrendingDown } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { cn, formatCurrency, formatPercent, formatLargeNumber } from '@/lib/utils'
import type { Stock } from '@/types'

interface SearchResponse {
  data: Stock[]
  meta: {
    count: number
    query: string
    rateLimit: {
      used: number
      limit: number
      remaining: number
    }
  }
}

interface StockSearchProps {
  /** Placeholder text for the search input */
  placeholder?: string
  /** Auto-focus the input on mount */
  autoFocus?: boolean
  /** Callback when a stock is selected */
  onSelect?: (stock: Stock) => void
  /** Additional class names for the container */
  className?: string
}

export function StockSearch({
  placeholder = 'Ticker or company name',
  autoFocus = false,
  onSelect,
  className,
}: StockSearchProps) {
  const router = useRouter()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Stock[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)

  const resultId = useId()
  const requestId = useRef(0)
  const controller = useRef<AbortController | null>(null)
  useEffect(
    () => () => {
      requestId.current++
      controller.current?.abort()
    },
    []
  )
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Perform search (only called on Enter)
  const performSearch = useCallback(async (searchQuery: string) => {
    if (!searchQuery.trim()) {
      setResults([])
      setIsOpen(false)
      return
    }

    const id = ++requestId.current
    controller.current?.abort()
    controller.current = new AbortController()
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(
        `/api/stock/search?query=${encodeURIComponent(searchQuery.trim())}`,
        { signal: AbortSignal.any([controller.current.signal, AbortSignal.timeout(10000)]) }
      )

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'Search failed')
      }

      const data: SearchResponse = await response.json()
      if (id !== requestId.current) return
      setResults(data.data)
      setIsOpen(data.data.length > 0 || data.data.length === 0)
      setSelectedIndex(-1)
    } catch (err) {
      if (id !== requestId.current) return
      setError(err instanceof Error ? err.message : 'Search failed')
      setResults([])
      setIsOpen(false)
    } finally {
      if (id === requestId.current) setIsLoading(false)
    }
  }, [])

  // Handle input change - just update state, auto-capitalize
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value.toUpperCase()
      requestId.current++
      controller.current?.abort()
      setIsLoading(false)
      setIsOpen(false)
      setResults([])
      setQuery(value)
      // Clear error when user types
      if (error) {
        setError(null)
      }
    },
    [error]
  )

  // Handle stock selection
  const handleSelectStock = useCallback(
    (stock: Stock) => {
      setQuery(stock.ticker)
      setIsOpen(false)
      setResults([])

      if (onSelect) {
        onSelect(stock)
      } else {
        // Default behavior: navigate to stock page
        router.push(
          `/stock/${stock.ticker}?from=${encodeURIComponent(window.location.pathname + window.location.search)}`
        )
      }
    },
    [onSelect, router]
  )

  // Handle keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case 'Enter':
          e.preventDefault()
          if (isOpen && selectedIndex >= 0 && selectedIndex < results.length) {
            // If a result is selected, navigate to it
            handleSelectStock(results[selectedIndex])
          } else if (query.trim()) {
            // Otherwise, perform search
            performSearch(query)
          }
          break
        case 'ArrowDown':
          if (isOpen && results.length > 0) {
            e.preventDefault()
            setSelectedIndex((prev) => (prev < results.length - 1 ? prev + 1 : prev))
          }
          break
        case 'ArrowUp':
          if (isOpen && results.length > 0) {
            e.preventDefault()
            setSelectedIndex((prev) => (prev > 0 ? prev - 1 : -1))
          }
          break
        case 'Escape':
          e.preventDefault()
          setIsOpen(false)
          setSelectedIndex(-1)
          break
      }
    },
    [isOpen, results, selectedIndex, handleSelectStock, performSearch, query]
  )

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
        setSelectedIndex(-1)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div ref={containerRef} className={cn('relative w-full', className)}>
      {/* Search Input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length > 0 && setIsOpen(true)}
          placeholder={placeholder}
          autoFocus={autoFocus}
          className="pl-10 pr-24 h-12 text-base"
          aria-label="Search stocks"
          aria-controls={resultId}
          aria-activedescendant={
            isOpen && selectedIndex >= 0 ? `${resultId}-${selectedIndex}` : undefined
          }
          aria-expanded={isOpen}
          aria-haspopup="listbox"
          role="combobox"
        />
        <button
          type="button"
          disabled={isLoading || !query.trim()}
          onClick={() => void performSearch(query)}
          className="absolute right-1 top-1 min-h-10 rounded bg-primary px-3 text-sm text-primary-foreground disabled:opacity-50"
        >
          {isLoading ? '…' : 'Search'}
        </button>
      </div>

      {/* Error Message */}
      {error && (
        <div
          role="alert"
          className="absolute z-50 mt-1 w-full rounded-md border bg-destructive/10 p-3 text-sm text-destructive"
        >
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Results Dropdown */}
      {isOpen && results.length > 0 && (
        <ul
          className="absolute z-50 mt-1 max-h-80 w-full overflow-auto rounded-md border bg-popover p-1 shadow-lg"
          id={resultId}
          role="listbox"
        >
          {results.map((stock, index) => (
            <li
              key={stock.ticker}
              id={`${resultId}-${index}`}
              role="option"
              aria-selected={index === selectedIndex}
              className={cn(
                'flex cursor-pointer items-center justify-between rounded-sm px-3 py-2 text-sm transition-colors',
                index === selectedIndex
                  ? 'bg-accent text-accent-foreground'
                  : 'hover:bg-accent hover:text-accent-foreground'
              )}
              onClick={() => handleSelectStock(stock)}
              onMouseEnter={() => setSelectedIndex(index)}
            >
              <div className="flex flex-col">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{stock.ticker}</span>
                  <span className="text-muted-foreground truncate max-w-[130px] sm:max-w-[200px]">
                    {stock.name}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{stock.sector}</span>
                  <span>•</span>
                  <span>
                    {stock.marketCap == null ? stock.exchange : formatLargeNumber(stock.marketCap)}
                  </span>
                </div>
              </div>
              <div className="flex flex-col items-end">
                <span className="font-medium">
                  {stock.price == null ? 'Quote unavailable' : formatCurrency(stock.price)}
                </span>
                <div
                  className={cn(
                    'flex items-center gap-1 text-xs',
                    stock.changePercent == null
                      ? 'text-muted-foreground'
                      : stock.changePercent >= 0
                        ? 'text-gain'
                        : 'text-loss'
                  )}
                >
                  {stock.changePercent == null ? null : stock.changePercent >= 0 ? (
                    <TrendingUp className="h-3 w-3" />
                  ) : (
                    <TrendingDown className="h-3 w-3" />
                  )}
                  <span>
                    {stock.changePercent == null ? '—' : formatPercent(stock.changePercent)}
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* No Results Message */}
      {isOpen && results.length === 0 && query.trim() && !isLoading && !error && (
        <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover p-4 text-center text-sm text-muted-foreground shadow-lg">
          No stocks found matching &quot;{query}&quot;
        </div>
      )}
    </div>
  )
}
