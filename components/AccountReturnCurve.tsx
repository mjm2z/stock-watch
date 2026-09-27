'use client'
import { useState } from 'react'
export type ReturnPoint = { at: string; index: number | null }
export function AccountReturnCurve({ points }: { points: ReturnPoint[] }) {
  const [selected, setSelected] = useState<number | null>(null)
  const valid = points.filter((p) => p.index !== null && Number.isFinite(p.index))
  if (valid.length < 2)
    return (
      <p className="text-sm text-muted-foreground">
        A return curve needs two complete account valuations.
      </p>
    )
  const low = Math.min(100, ...valid.map((p) => p.index!)),
    high = Math.max(100, ...valid.map((p) => p.index!))
  const start = Date.parse(points[0].at),
    span = Date.parse(points[points.length - 1].at) - start || 1
  const x = (p: ReturnPoint) => 20 + ((Date.parse(p.at) - start) / span) * 760
  const y = (value: number) => 180 - ((value - low) / (high - low || 1)) * 150
  let connected = false
  const path = points
    .map((p) => {
      if (p.index === null) {
        connected = false
        return ''
      }
      const command = connected ? 'L' : 'M'
      connected = true
      return `${command}${x(p)},${y(p.index)}`
    })
    .join(' ')
  const current = points[Math.min(selected ?? points.length - 1, points.length - 1)]
  return (
    <div className="space-y-2">
      <p className="text-sm">
        {current.at} · Return index{' '}
        {current.index === null ? 'unavailable' : current.index.toFixed(2)} · Starting value 100
      </p>
      <svg
        viewBox="0 0 800 200"
        className="h-auto w-full"
        role="img"
        aria-label="Cash-flow-adjusted account return index"
        onMouseMove={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect()
          const time =
            start + ((((event.clientX - bounds.left) / bounds.width) * 800 - 20) / 760) * span
          setSelected(
            points.reduce(
              (best, p, i) =>
                Math.abs(Date.parse(p.at) - time) < Math.abs(Date.parse(points[best].at) - time)
                  ? i
                  : best,
              0
            )
          )
        }}
        onMouseLeave={() => setSelected(null)}
      >
        <line
          x1="20"
          x2="780"
          y1={y(100)}
          y2={y(100)}
          stroke="currentColor"
          opacity=".2"
          strokeDasharray="4 4"
        />
        <path d={path} fill="none" stroke="currentColor" strokeWidth="2" />
        {current.index !== null && (
          <circle cx={x(current)} cy={y(current.index)} r="4" fill="currentColor" />
        )}
      </svg>
      <label className="text-sm text-muted-foreground">
        Inspect account observation
        <input
          className="w-full"
          type="range"
          min="0"
          max={points.length - 1}
          value={selected ?? points.length - 1}
          onChange={(e) => setSelected(Number(e.target.value))}
        />
      </label>
      <p className="text-xs text-muted-foreground">
        Latest {points.length} retained observations (up to 500), without interpolation across
        unavailable measurements. Headline return and drawdown use the full retained period.
      </p>
    </div>
  )
}
