'use client'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { formatTimestamp } from '@/lib/utils'
import { useSharedWatchlist } from '@/lib/use-shared-watchlist'
interface Note {
  id: string
  ticker: string
  created_at: string
  hypothesis: string
  evidence: string
  contrary_evidence: string
  horizon: number
  review_on: string
  assessment: string
}
export function ResearchJournal({ symbol = '' }: { symbol?: string }) {
  const [notes, setNotes] = useState<Note[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [retry, setRetry] = useState(0)
  const [message, setMessage] = useState('')
  const { add } = useSharedWatchlist()
  const refresh = useCallback(async () => {
    const response = await fetch(`/api/research?symbol=${encodeURIComponent(symbol)}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(10000),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.error)
    setNotes(data.notes)
  }, [symbol])
  useEffect(() => {
    setLoading(true)
    setLoadFailed(false)
    void refresh()
      .catch((e) => {
        setError(e.message)
        setLoadFailed(true)
      })
      .finally(() => setLoading(false))
  }, [refresh, retry])
  async function importWatchlist() {
    setBusy(true)
    setError(null)
    setMessage('')
    try {
      const items = JSON.parse(localStorage.getItem('stock-watch-watchlist') ?? '[]')
      if (!Array.isArray(items) || items.length > 500)
        throw new Error('Browser watchlist is invalid or too large.')
      for (const item of items) {
        if (!item || typeof item.ticker !== 'string' || !(await add(item.ticker, item.notes ?? '')))
          throw new Error(
            'Import stopped. Retry to import the remaining entries; existing entries are preserved.'
          )
      }
      setMessage(
        `Imported ${items.length} browser watchlist entries. The original browser data is preserved.`
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Import failed.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Research journal</h2>
        <details>
          <summary className="text-sm">Journal tools</summary>
          <button
            disabled={busy}
            onClick={() => void importWatchlist()}
            className="rounded-md border px-3 py-2 text-sm disabled:opacity-50"
          >
            Import this browser’s old watchlist
          </button>
        </details>
      </div>
      <p className="text-sm text-muted-foreground">
        Record a thesis, contrary evidence, and a review date. Entries are append-only so you can
        compare your original reasoning with later results. Shared with everyone on this LAN.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="text-sm text-primary">
          {message}
        </p>
      )}
      <form
        className="grid gap-4 rounded-xl border bg-card p-5 sm:grid-cols-2"
        onSubmit={async (event) => {
          event.preventDefault()
          const form = event.currentTarget
          setBusy(true)
          setError(null)
          setMessage('')
          try {
            const body = Object.fromEntries(new FormData(form))
            const response = await fetch('/api/research', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ...body, action: 'note' }),
            })
            const data = await response.json()
            if (!response.ok) throw new Error(data.error)
            form.reset()
            setMessage('Research entry saved.')
            try {
              await refresh()
            } catch {
              setMessage('Research entry saved. The list could not refresh; reload to see it.')
            }
          } catch (e) {
            setError(e instanceof Error ? e.message : 'Save failed.')
          } finally {
            setBusy(false)
          }
        }}
      >
        <label className="text-sm">
          Ticker
          <input
            required
            name="ticker"
            defaultValue={symbol}
            maxLength={10}
            className="mt-1 block w-full rounded-md border bg-background p-2 uppercase"
          />
        </label>
        <label className="text-sm">
          Holding horizon
          <select name="horizon" className="mt-1 block w-full rounded-md border bg-background p-2">
            {[5, 21, 63, 105].map((n) => (
              <option key={n} value={n}>
                {n} trading days
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm sm:col-span-2">
          Hypothesis
          <textarea
            required
            maxLength={5000}
            name="hypothesis"
            rows={3}
            className="mt-1 block w-full rounded-md border bg-background p-2"
          />
        </label>
        <label className="text-sm">
          Supporting evidence
          <textarea
            maxLength={5000}
            name="evidence"
            rows={3}
            className="mt-1 block w-full rounded-md border bg-background p-2"
          />
        </label>
        <label className="text-sm">
          Contrary evidence / what would invalidate it
          <textarea
            maxLength={5000}
            name="contrary_evidence"
            rows={3}
            className="mt-1 block w-full rounded-md border bg-background p-2"
          />
        </label>
        <label className="text-sm">
          Review on
          <input
            required
            name="review_on"
            type="date"
            className="mt-1 block w-full rounded-md border bg-background p-2"
          />
        </label>
        <label className="text-sm">
          Current assessment
          <select
            name="assessment"
            className="mt-1 block w-full rounded-md border bg-background p-2"
          >
            {['open', 'supported', 'mixed', 'invalidated'].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <button
          disabled={busy}
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
        >
          {busy ? 'Saving…' : 'Save research entry'}
        </button>
      </form>
      <div className="grid gap-4 lg:grid-cols-2">
        {notes.map((note) => (
          <article key={note.id} className="space-y-3 rounded-xl border bg-card p-5">
            <div className="flex justify-between gap-3">
              <Link className="font-semibold text-primary" href={`/stock/${note.ticker}`}>
                {note.ticker} · {note.horizon}d
              </Link>
              <span className="text-sm capitalize">{note.assessment}</span>
            </div>
            <p className="text-xs text-muted-foreground">
              {formatTimestamp(note.created_at)} ET · Review {note.review_on}
            </p>
            <p className="whitespace-pre-wrap text-sm">{note.hypothesis}</p>
            {note.assessment === 'open' &&
              note.review_on <
                new Intl.DateTimeFormat('en-CA', {
                  timeZone: 'America/New_York',
                  year: 'numeric',
                  month: '2-digit',
                  day: '2-digit',
                }).format(new Date()) && (
                <p className="text-sm text-amber-700">
                  Review overdue · Add a follow-up entry to record your reassessment.
                </p>
              )}
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">
              <strong>Evidence:</strong> {note.evidence || 'Not recorded'}
            </p>
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">
              <strong>Contrary evidence:</strong> {note.contrary_evidence || 'Not recorded'}
            </p>
            <Link
              className="text-xs text-primary underline"
              href={`/signals?symbol=${encodeURIComponent(note.ticker)}&horizon=${note.horizon}`}
            >
              Compare signal decisions and outcomes
            </Link>
          </article>
        ))}
      </div>
      {loading && (
        <p role="status" className="text-sm">
          Loading journal entries…
        </p>
      )}
      {loadFailed && (
        <button className="min-h-11 underline" onClick={() => setRetry((n) => n + 1)}>
          Retry loading journal
        </button>
      )}
      {!loading && !loadFailed && !notes.length && (
        <p className="text-sm text-muted-foreground">No journal entries in this view yet.</p>
      )}
      <p className="text-xs text-muted-foreground">
        Showing the 100 most recent entries{symbol ? ` for ${symbol}` : ''}.
      </p>
    </section>
  )
}
