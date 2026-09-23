import type { DashboardSignal } from '@/types/dashboard'

/** Inclusive Eastern calendar date; next=true returns the following midnight, including DST. */
export function easternDayBoundary(day: string, next = false): string {
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(day) ||
    !Number.isFinite(Date.parse(day)) ||
    new Date(day).toISOString().slice(0, 10) !== day
  )
    throw new Error('Enter a valid calendar date.')
  const date = new Date(`${day}T00:00:00Z`)
  if (next) date.setUTCDate(date.getUTCDate() + 1)
  const offset = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    timeZoneName: 'shortOffset',
  })
    .formatToParts(new Date(date.getTime() + 5 * 3600000))
    .find((part) => part.type === 'timeZoneName')?.value
  const hours = Number(offset?.replace('GMT', ''))
  if (!Number.isFinite(hours)) throw new Error('Eastern timezone unavailable.')
  return new Date(date.getTime() - hours * 3600000).toISOString()
}

export function incidentText(error: string): string {
  if (error.includes('immutable news article changed'))
    return 'The scan stopped when a previously collected news article changed.'
  return 'This operation did not complete. Review the technical details for the recorded cause.'
}

export function executionLabel(signal: DashboardSignal): string {
  if (signal.orderStatus) return `Order: ${signal.orderStatus.replaceAll('_', ' ')}`
  if (signal.qualityReview?.blockers.length) return 'Blocked by data checks'
  if (signal.decision === 'rejected') return 'Not selected'
  return 'No order recorded'
}

export const commandLabels: Record<string, string> = {
  'work-once': 'Scheduled scan',
  'dispatch-once': 'Schedule dispatch',
  'exit-once': 'Exit checks',
  'maintain-paper': 'Portfolio reconciliation and evaluation',
  'refresh-fundamentals': 'Company financials refresh',
}
