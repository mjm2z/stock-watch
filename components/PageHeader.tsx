import type { ReactNode } from 'react'
export function PageHeader({
  title,
  description,
  action,
  compact = false,
}: {
  title: string
  description: string
  action?: ReactNode
  compact?: boolean
}) {
  return (
    <header className={`sw-page-header${compact ? ' sw-overview-header' : ''}`}>
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="sw-page-action">{action}</div>}
    </header>
  )
}
