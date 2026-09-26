'use client'
import { useState } from 'react'
import { money } from './ResearchActivity'
export function BacktestCurve({ rows }: { rows: any[] }) {
  const [selected, setSelected] = useState<number | null>(null)
  const points = (rows || []).filter((r) => Number.isFinite(r.equity))
  if (points.length < 2) return <p className="sw-muted">No equity curve available.</p>
  const lo = Math.min(...points.map((r) => r.equity)),
    hi = Math.max(...points.map((r) => r.equity)),
    spread = hi - lo || 1
  const x = (i: number) => 20 + (i / (points.length - 1)) * 760,
    y = (v: number) => 180 - ((v - lo) / spread) * 150
  const current = points[selected ?? points.length - 1]
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-sm">
        <span>
          {current.at} · Equity {money(current.equity)}
        </span>
        <span>
          Range {money(lo)}–{money(hi)}
        </span>
      </div>
      <svg
        viewBox="0 0 800 200"
        className="w-full h-auto"
        role="img"
        aria-label="Historical modeled equity curve"
        onMouseMove={(e) => {
          const b = e.currentTarget.getBoundingClientRect()
          setSelected(
            Math.max(
              0,
              Math.min(
                points.length - 1,
                Math.round(
                  ((((e.clientX - b.left) / b.width) * 800 - 20) / 760) * (points.length - 1)
                )
              )
            )
          )
        }}
        onMouseLeave={() => setSelected(null)}
      >
        <path
          d={points.map((p, i) => (i ? 'L' : 'M') + x(i) + ',' + y(p.equity)).join(' ')}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        />
        {selected !== null && (
          <>
            <line
              x1={x(selected)}
              x2={x(selected)}
              y1="15"
              y2="185"
              stroke="currentColor"
              opacity=".25"
            />
            <circle cx={x(selected)} cy={y(current.equity)} r="4" fill="currentColor" />
          </>
        )}
      </svg>
      <label className="sw-muted">
        Inspect a point
        <input
          type="range"
          min={0}
          max={points.length - 1}
          value={selected ?? points.length - 1}
          onChange={(e) => setSelected(Number(e.target.value))}
          className="w-full"
        />
      </label>
      <p className="sw-muted">
        Display sample of the full curve. Download evidence for every recorded point.
      </p>
    </div>
  )
}
