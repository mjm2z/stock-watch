export const DAY = 86_400_000
export type HistoryWindow = { start: number; end: number }
export function initialWindow(
  asset: string,
  range: string,
  custom: { start: string; end: string },
  now: number
): HistoryWindow {
  if (range.toUpperCase() === 'CUSTOM')
    return { start: Date.parse(custom.start), end: Date.parse(custom.end) }
  const days: Record<string, number> = {
    '1D': asset === 'stocks' ? 4 : 1,
    '1W': 7,
    '1M': 32,
    '3M': 95,
    '6M': 184,
    '1Y': 370,
    '5Y': 1830,
    '10Y': 3653,
    '30Y': 10958,
    ALL: 3650,
  }
  const end = Math.floor(now / 300000) * 300000
  return { start: end - (days[range.toUpperCase()] || 32) * DAY, end }
}
export function windowResolution(asset: string, window: HistoryWindow, range: string) {
  const days = (window.end - window.start) / DAY
  if (asset === 'bitcoin')
    return days <= 2 ? '5Min' : days <= 32 ? '1Hour' : days <= 190 ? '4Hour' : '1Day'
  const initial =
    range.toUpperCase() === '1D' ? '5Min' : range.toUpperCase() === '1W' ? '1Hour' : '1Day'
  return initial === '5Min' && days <= 20
    ? '5Min'
    : initial !== '1Day' && days <= 240
      ? '1Hour'
      : '1Day'
}
export function extendWindow(
  current: HistoryWindow,
  visible: HistoryWindow,
  asset: string,
  now: number
): HistoryWindow {
  const earliest = now - (asset === 'bitcoin' ? 3660 : 10958) * DAY
  const span = Math.max(DAY, current.end - current.start)
  return {
    start: Math.max(
      earliest,
      visible.start < current.start
        ? Math.min(visible.start, current.start - span / 2)
        : current.start
    ),
    end: Math.min(
      now,
      visible.end > current.end ? Math.max(visible.end, current.end + span / 2) : current.end
    ),
  }
}
export function mergeBars<T extends { at: string }>(old: T[], next: T[]): T[] {
  return [...new Map([...old, ...next].map((b) => [b.at, b])).values()].sort((a, b) =>
    a.at.localeCompare(b.at)
  )
}
