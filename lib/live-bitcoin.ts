'use client'
import { useSyncExternalStore } from 'react'
export type LiveSnapshot = {
  price: number | null
  fresh: boolean
  status: string
  sourceAt: string | null
  receivedAt: number | null
  heartbeatAt: number
  generation?: string
  id?: string
  direction?: string
}
let snapshot: LiveSnapshot | null = null
let source: EventSource | null = null
let timer: ReturnType<typeof setInterval> | null = null
const listeners = new Set<() => void>()
const emit = (value: LiveSnapshot) => {
  snapshot = value
  for (const listener of listeners) listener()
}
function start() {
  source = new EventSource('/api/crypto/live?stream=1')
  source.onmessage = (event) => {
    try {
      const next: LiveSnapshot = JSON.parse(event.data)
      if (next.price !== null && (!Number.isFinite(next.price) || next.price <= 0)) return
      if (next.sourceAt && !Number.isFinite(Date.parse(next.sourceAt))) return
      // A new collector may reset generation; source time still prevents old prices
      // replacing newer observations within the same connection generation.
      if (
        snapshot?.generation === next.generation &&
        snapshot?.sourceAt &&
        next.sourceAt &&
        Date.parse(next.sourceAt) < Date.parse(snapshot.sourceAt)
      )
        return
      const previous = snapshot?.price
      const direction =
        previous == null || next.price == null
          ? '—'
          : previous === next.price
            ? snapshot?.direction
            : next.price > previous
              ? '↑'
              : '↓'
      emit({ ...next, direction }) // Each event is delivered immediately; no display debounce.
    } catch {
      /* Keep the last valid observed price. */
    }
  }
  source.onerror = () =>
    emit({
      price: null,
      sourceAt: null,
      receivedAt: null,
      heartbeatAt: 0,
      ...snapshot,
      fresh: false,
      status: 'Reconnecting',
    })
  timer = setInterval(() => {
    if (
      snapshot?.fresh &&
      (!snapshot.sourceAt ||
        Date.now() - Date.parse(snapshot.sourceAt) > 5000 ||
        Date.now() - snapshot.heartbeatAt > 3000)
    )
      emit({ ...snapshot, fresh: false, status: 'Stale' })
  }, 250) // Freshness clock only; this never polls or delays tick delivery.
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  if (!source) start()
  return () => {
    listeners.delete(listener)
    if (!listeners.size) {
      source?.close()
      source = null
      if (timer) clearInterval(timer)
      timer = null
      snapshot = null
    }
  }
}
const getSnapshot = () => snapshot
const serverSnapshot = () => null
export function useLiveBitcoin() {
  return useSyncExternalStore(subscribe, getSnapshot, serverSnapshot)
}
