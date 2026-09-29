export type ChartEvent = {
  id: string
  at: string
  label: string
  side?: string
  price?: number
  evidence: unknown
}
// Markers are grouped only for presentation. Exact timestamps remain on events.
export function groupChartEvents(times: number[], events: ChartEvent[]) {
  const groups = new Map<number, ChartEvent[]>()
  if (!times.length) return groups
  for (const event of events) {
    const at = Date.parse(event.at) / 1000
    if (!Number.isFinite(at) || at < times[0] || at > times[times.length - 1]) continue
    let lo = 0,
      hi = times.length - 1
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2)
      if (times[mid] <= at) lo = mid
      else hi = mid - 1
    }
    const bucket = groups.get(times[lo]) || []
    if (!bucket.some((e) => e.id === event.id)) bucket.push(event)
    groups.set(times[lo], bucket)
  }
  return groups
}
