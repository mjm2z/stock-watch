'use client'
type Point = { at: string; equity: number }
export function SystemEquityChart({ points }: { points: unknown }) {
  if (!Array.isArray(points)) return null
  const series = points.filter(
    (p): p is Point =>
      p && typeof p.at === 'string' && typeof p.equity === 'number' && Number.isFinite(p.equity)
  )
  if (series.length < 2) return null
  const low = Math.min(300, ...series.map((p) => p.equity))
  const high = Math.max(300, ...series.map((p) => p.equity))
  const span = Math.max(1, high - low)
  const first = Date.parse(series[0].at),
    last = Date.parse(series[series.length - 1].at)
  const y = (value: number) => 150 - ((value - low) / span) * 130
  const path = series
    .map(
      (p) => `${35 + ((Date.parse(p.at) - first) / Math.max(1, last - first)) * 580},${y(p.equity)}`
    )
    .join(' ')
  return (
    <figure className="rounded-lg bg-muted/30 p-3">
      <figcaption className="mb-2 text-sm">
        Cash-constrained equity · $300 starting capital · Downsampled for display
      </figcaption>
      <svg
        viewBox="0 0 650 185"
        role="img"
        aria-label={`Research equity from $${series[0].equity.toFixed(2)} to $${series[series.length - 1].equity.toFixed(2)}`}
        className="w-full"
      >
        <line
          x1="35"
          y1={y(300)}
          x2="615"
          y2={y(300)}
          stroke="currentColor"
          opacity="0.3"
          strokeDasharray="4 4"
        />
        <polyline
          points={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="text-primary"
        />
        <text x="0" y="18" fontSize="11" fill="currentColor">
          ${high.toFixed(0)}
        </text>
        <text x="0" y="151" fontSize="11" fill="currentColor">
          ${low.toFixed(0)}
        </text>
        <text x="35" y="178" fontSize="11" fill="currentColor">
          {series[0].at.slice(0, 10)}
        </text>
        <text x="615" y="178" fontSize="11" fill="currentColor" textAnchor="end">
          {series[series.length - 1].at.slice(0, 10)}
        </text>
      </svg>
    </figure>
  )
}
