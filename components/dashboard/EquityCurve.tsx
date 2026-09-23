'use client'
import { useState } from 'react'
import type { DashboardPortfolio } from '@/types/dashboard'
import { formatCurrency, formatTimestamp } from '@/lib/utils'
import { utcMillis } from '@/lib/execution-status-model'
export function EquityCurve({ history }: { history: DashboardPortfolio['history'] }) {
  const [selected, setSelected] = useState<number | null>(null)
  if (history.length < 2)
    return (
      <p className="rounded-lg bg-muted/40 p-6 text-sm text-muted-foreground">
        At least two valued snapshots are needed for a chart. Current results appear above when
        available.
      </p>
    )
  const values = history.flatMap((p) =>
    p.spyValue === null
      ? [p.equity, p.contributedCapital]
      : [p.equity, p.spyValue, p.contributedCapital]
  )
  const min = Math.min(...values),
    max = Math.max(...values),
    range = max - min || 1
  const start = utcMillis(history[0].observedAt),
    end = utcMillis(history.at(-1)!.observedAt)
  const x = (i: number) =>
    65 + ((utcMillis(history[i].observedAt) - start) / (end - start || 1)) * 710
  const y = (v: number) => 215 - ((v - min) / range) * 185
  const path = (pick: (p: (typeof history)[number]) => number | null) => {
    let connected = false
    return history
      .map((p, i) => {
        const v = pick(p)
        if (v === null) {
          connected = false
          return ''
        }
        const command = connected ? 'L' : 'M'
        connected = true
        return `${command}${x(i)},${y(v)}`
      })
      .join(' ')
  }
  const index = Math.min(selected ?? history.length - 1, history.length - 1),
    point = history[index]
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-4 text-sm">
        <span>━ Paper equity</span>
        <span className="text-slate-500">┄ Matched SPY</span>
        <span className="text-amber-700">··· Contributions</span>
      </div>
      <svg
        viewBox="0 0 800 250"
        className="w-full"
        role="img"
        aria-label="Paper equity, matched SPY, and contributed capital over time. Use the snapshot selector for exact values."
      >
        {[min, (min + max) / 2, max].map((v, i) => (
          <g key={i}>
            <line x1="65" x2="775" y1={y(v)} y2={y(v)} stroke="currentColor" opacity="0.1" />
            <text x="2" y={y(v) + 4} fontSize="12" fill="currentColor">
              {formatCurrency(v)}
            </text>
          </g>
        ))}
        <path d={path((p) => p.equity)} fill="none" stroke="currentColor" strokeWidth="2" />
        <path
          d={path((p) => p.spyValue)}
          fill="none"
          stroke="#64748b"
          strokeWidth="2"
          strokeDasharray="6 4"
        />
        <path
          d={path((p) => p.contributedCapital)}
          fill="none"
          stroke="#b45309"
          strokeWidth="2"
          strokeDasharray="2 4"
        />
        <line x1={x(index)} x2={x(index)} y1="20" y2="215" stroke="currentColor" opacity="0.3" />
        <text x="65" y="243" fontSize="12" fill="currentColor">
          {formatTimestamp(history[0].observedAt).split(',')[0]}
        </text>
        <text x="775" y="243" textAnchor="end" fontSize="12" fill="currentColor">
          {formatTimestamp(history.at(-1)!.observedAt).split(',')[0]}
        </text>
      </svg>
      <label className="block text-sm">
        Inspect snapshot
        <input
          aria-label="Snapshot"
          type="range"
          min="0"
          max={history.length - 1}
          value={index}
          onChange={(event) => setSelected(Number(event.target.value))}
          className="mt-2 w-full"
        />
      </label>
      <p className="text-sm" aria-live="polite">
        {formatTimestamp(point.observedAt)} ET · Equity {formatCurrency(point.equity)} · SPY{' '}
        {point.spyValue === null ? 'Unavailable' : formatCurrency(point.spyValue)} · Contributions{' '}
        {formatCurrency(point.contributedCapital)}
      </p>
      <p className="text-xs text-muted-foreground">
        Latest {history.length} snapshots. Contribution increases are deposits, not returns. Gaps in
        SPY indicate missing benchmark values.
      </p>
    </div>
  )
}
