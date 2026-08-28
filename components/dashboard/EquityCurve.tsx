import type { DashboardPortfolio } from '@/types/dashboard'

export function EquityCurve({ history }: { history: DashboardPortfolio['history'] }) {
  if (history.length < 2) {
    return (
      <div className="flex h-52 items-center justify-center rounded-lg bg-muted/40 text-sm text-muted-foreground">
        Equity history will appear after portfolio snapshots are collected.
      </div>
    )
  }
  const width = 800
  const height = 220
  const values = history.flatMap(point =>
    point.spyValue === null ? [point.equity] : [point.equity, point.spyValue]
  )
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  const range = maximum - minimum || 1
  const points = (selector: (point: (typeof history)[number]) => number | null) =>
    history
      .map((point, index) => {
        const value = selector(point)
        if (value === null) return null
        const x = (index / (history.length - 1)) * width
        const y = height - ((value - minimum) / range) * height
        return `${x.toFixed(1)},${y.toFixed(1)}`
      })
      .filter(Boolean)
      .join(' ')

  return (
    <div>
      <div className="mb-3 flex gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-2"><i className="h-0.5 w-5 bg-primary" />Paper equity</span>
        <span className="flex items-center gap-2"><i className="h-0.5 w-5 bg-slate-400" />Contribution-matched SPY</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-52 w-full overflow-visible" role="img">
        <title>Paper account equity compared with SPY</title>
        <polyline fill="none" stroke="currentColor" strokeWidth="3" points={points(p => p.equity)} />
        <polyline
          fill="none"
          stroke="rgb(148 163 184)"
          strokeWidth="2"
          strokeDasharray="6 6"
          points={points(p => p.spyValue)}
        />
      </svg>
    </div>
  )
}
