'use client'
import { useRef, useState } from 'react'
export type ChartStyle = 'candles' | 'hollow' | 'line' | 'bars'
export function ChartControls({
  range,
  onRange,
  ranges,
  custom,
  onCustom,
  style,
  onStyle,
  volume,
  onVolume,
  multiple = false,
  hideStyle = false,
}: {
  range: string
  onRange: (r: string) => void
  ranges: string[]
  custom: { start: string; end: string }
  onCustom: (d: { start: string; end: string }) => void
  style: ChartStyle
  onStyle: (s: ChartStyle) => void
  volume: boolean
  onVolume: () => void
  hideStyle?: boolean
  multiple?: boolean
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [start, setStart] = useState(''),
    [end, setEnd] = useState(''),
    [error, setError] = useState('')
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const close = () => {
    dialog.current?.close()
    trigger.current?.focus()
  }
  return (
    <div className="sw-chart-controls">
      <div className="sw-range-buttons" aria-label="Price history range">
        {ranges.map((r) => (
          <button key={r} aria-pressed={range === r} onClick={() => onRange(r)}>
            {r === 'ALL' ? 'All' : r}
          </button>
        ))}
        <button
          ref={trigger}
          aria-haspopup="dialog"
          aria-pressed={range.toUpperCase() === 'CUSTOM'}
          onClick={() => {
            setStart(custom.start.slice(0, 10))
            setEnd(
              custom.end ? new Date(Date.parse(custom.end) - 1).toISOString().slice(0, 10) : ''
            )
            setError('')
            const rect = trigger.current!.getBoundingClientRect()
            setPosition({
              top: Math.max(16, Math.min(rect.bottom + 8, window.innerHeight - 310)),
              left: Math.max(16, Math.min(rect.left, window.innerWidth - 406)),
            })
            dialog.current?.showModal()
          }}
        >
          Custom
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {!hideStyle && <ChartStyleSelect style={style} onStyle={onStyle} multiple={multiple} />}
        <button className="sw-chart-text-button" aria-pressed={volume} onClick={onVolume}>
          {volume ? 'Hide volume' : 'Show volume'}
        </button>
      </div>
      <dialog
        ref={dialog}
        style={{ ...position, margin: 0, position: 'fixed' }}
        className="sw-date-popover"
        aria-label="Custom date range"
        onClick={(e) => {
          if (e.target === dialog.current) close()
        }}
        onCancel={() => trigger.current?.focus()}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault()
            const a = Date.parse(start + 'T00:00:00Z'),
              b = Math.min(Date.parse(end + 'T00:00:00Z') + 86400000, Date.now())
            if (!Number.isFinite(a) || !Number.isFinite(b) || a >= b) {
              setError('Choose a start date on or before the end date.')
              return
            }
            onCustom({ start: new Date(a).toISOString(), end: new Date(b).toISOString() })
            onRange('custom')
            close()
          }}
        >
          <h3 className="font-semibold">Custom range</h3>
          <p className="text-xs text-muted-foreground">Start and end dates included · UTC</p>
          <div className="my-4 grid grid-cols-2 gap-3">
            {(['Start', 'End'] as const).map((label) => (
              <label key={label} className="sw-field">
                {label}
                <input
                  required
                  type="date"
                  max={new Date().toISOString().slice(0, 10)}
                  value={label === 'Start' ? start : end}
                  onChange={(e) =>
                    label === 'Start' ? setStart(e.target.value) : setEnd(e.target.value)
                  }
                />
              </label>
            ))}
          </div>
          {error && <p role="alert">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" className="sw-button" onClick={close}>
              Cancel
            </button>
            <button className="sw-button">Apply</button>
          </div>
        </form>
      </dialog>
    </div>
  )
}

export function ChartStyleSelect({
  style,
  onStyle,
  multiple = false,
}: {
  style: ChartStyle
  onStyle: (s: ChartStyle) => void
  multiple?: boolean
}) {
  return (
    <select
      aria-label="Chart style"
      value={style}
      disabled={multiple}
      title={multiple ? 'Multiple stocks use lines' : undefined}
      onChange={(e) => onStyle(e.target.value as ChartStyle)}
    >
      <option value="candles">Candles</option>
      <option value="hollow">Hollow candles</option>
      <option value="line">Lines</option>
      <option value="bars">Bars</option>
    </select>
  )
}
