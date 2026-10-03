import type { ReactNode } from 'react'
/** Separate axes so Firefox can hide the vertical track and retain horizontal navigation. */
export function TableScrollRegion({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Scrollable data table">
      <div className={`overflow-y-auto w-max min-w-full ${className}`} tabIndex={0}>
        {children}
      </div>
    </div>
  )
}
