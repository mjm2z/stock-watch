'use client'
import { useId, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function CompactDisclosure({
  title,
  summary,
  badge,
  children,
  className,
  compact = false,
}: {
  title: string
  summary?: string
  badge?: ReactNode
  children: ReactNode
  className?: string
  compact?: boolean
}) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <section
      className={cn(
        'min-w-0 overflow-hidden rounded-xl border border-border bg-card transition-colors',
        open && 'border-primary/30',
        className
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className={cn(
          'flex w-full items-center gap-3 text-left transition-colors hover:bg-muted/60',
          compact ? 'px-4 py-3' : 'px-5 py-4'
        )}
      >
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">{title}</span>
          {summary && (
            <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
              {summary}
            </span>
          )}
        </span>
        {badge}
        <span className="text-[11px] font-medium text-muted-foreground">
          {open ? 'Hide' : 'Show'}
        </span>
      </button>
      <div id={id} hidden={!open} className={cn('border-t border-border', compact ? 'p-4' : 'p-5')}>
        {open && children}
      </div>
    </section>
  )
}

export function StatusBadge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'good' | 'attention'
}) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full border px-2.5 py-1 text-[10px] font-medium leading-none',
        tone === 'good'
          ? 'border-primary/20 bg-primary/10 text-primary'
          : tone === 'attention'
            ? 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300'
            : 'border-border bg-muted/40 text-muted-foreground'
      )}
    >
      {children}
    </span>
  )
}

export function PagedRows<T>({
  items,
  render,
  label,
  pageSize = 3,
}: {
  items: T[]
  render: (item: T) => ReactNode
  label: string
  pageSize?: number
}) {
  const [requestedPage, setPage] = useState(0)
  const page = Math.min(requestedPage, Math.max(0, Math.ceil(items.length / pageSize) - 1))
  const start = page * pageSize
  return (
    <div className="min-w-0">
      <div className="divide-y divide-border">
        {items.slice(start, start + pageSize).map(render)}
      </div>
      {items.length > pageSize && (
        <nav
          aria-label={label + ' pages'}
          className="mt-3 flex items-center justify-between gap-3 border-t border-border pt-3 text-xs text-muted-foreground"
        >
          <span>
            {start + 1}–{Math.min(start + pageSize, items.length)} of {items.length}
          </span>
          <div className="flex gap-3">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
              className="rounded py-1 hover:text-foreground disabled:opacity-35"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={start + pageSize >= items.length}
              onClick={() => setPage(page + 1)}
              className="rounded py-1 hover:text-foreground disabled:opacity-35"
            >
              Next
            </button>
          </div>
        </nav>
      )}
    </div>
  )
}
