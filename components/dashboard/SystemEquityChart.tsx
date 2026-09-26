'use client'
import { useState } from 'react'
import { InteractiveChart, type ChartBar } from '../MarketChart'
export function SystemEquityChart({ points }: { points: unknown }) {
  const [drawdown, setDrawdown] = useState(false)
  if (!Array.isArray(points)) return null
  let peak = 0
  const bars: ChartBar[] = points
    .filter((p) => p && typeof p.at === 'string' && Number.isFinite(p.equity))
    .map((p) => {
      peak = Math.max(peak, p.equity)
      const value = drawdown
        ? typeof p.drawdown === 'number'
          ? p.drawdown
          : peak
            ? 100 * (p.equity / peak - 1)
            : 0
        : p.equity
      return { at: p.at, open: value, high: value, low: value, close: value, volume: 0 }
    })
  return bars.length > 1 ? (
    <figure>
      <div className="flex gap-2 mb-3">
        <button className="sw-button" aria-pressed={!drawdown} onClick={() => setDrawdown(false)}>
          Equity
        </button>
        <button className="sw-button" aria-pressed={drawdown} onClick={() => setDrawdown(true)}>
          Drawdown
        </button>
      </div>
      <figcaption className="sw-muted mb-3">
        Modeled portfolio · Sampled for display · Hover to inspect
      </figcaption>
      <InteractiveChart
        key={String(drawdown)}
        bars={bars}
        label={drawdown ? 'Drawdown' : 'Research equity'}
        percent={drawdown}
        height={260}
      />
    </figure>
  ) : (
    <p className="sw-muted">Not enough observations to chart yet.</p>
  )
}
