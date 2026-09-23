export interface MarketDay { date: string; open: string; close: string }
export interface ScanWindow { type: 'open' | 'close'; at: string }
export interface TimerHealth { name: string; active: boolean; checked: boolean; lastRun: string | null; result: string; exitCode: number | null; running: boolean }
export interface StatusScan { id: string; type: string; at: string; completedAt: string | null; status: string; strategyId: string; error: string | null }
export interface ExecutionSnapshot {
  strategyId: string | null; strategyStatus: string | null; strategySince: string | null; credentialsConfigured: boolean
  latestScan: StatusScan | null; lastSuccess: StatusScan | null; lastScheduledSuccess: StatusScan | null
  reconciliation: { status: string; at: string } | null
  ingestions: { dataset: string; at: string | null; status: string }[]
}
export interface ExecutionStatus extends ExecutionSnapshot {
  generatedAt: string; nextScan: ScanWindow | null; nextMaintenance: string | null
  state: 'ready' | 'running' | 'blocked' | 'attention' | 'unknown'
  issues: string[]; timers: TimerHealth[]; calendarAvailable: boolean
}
export function utcMillis(value: string | null): number {
  if (!value) return NaN
  return Date.parse(/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(value) ? value.replace(' ', 'T') + 'Z' : value)
}
// Exchange dates supply the session times. The NY offset is evaluated for that
// date, including DST; holidays are omitted by the provider, never guessed.
export function marketInstant(date: string, time: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}(:\d{2})?$/.test(time)) throw new Error('Invalid exchange session')
  const offset = new Intl.DateTimeFormat('en-US', { timeZone:'America/New_York', timeZoneName:'longOffset' })
    .formatToParts(new Date(date+'T12:00:00Z')).find(part => part.type === 'timeZoneName')?.value.replace('GMT','')
  if (!offset) throw new Error('Exchange timezone unavailable')
  return new Date(`${date}T${time.length === 5 ? time + ':00' : time}${offset}`).toISOString()
}
export function calendarWindows(days: MarketDay[]): ScanWindow[] {
  return days.flatMap(day => ([
    { type: 'open' as const, at: new Date(Date.parse(marketInstant(day.date,day.open)) + 900000).toISOString() },
    { type: 'close' as const, at: new Date(Date.parse(marketInstant(day.date,day.close)) + 900000).toISOString() },
  ])).sort((a,b) => utcMillis(a.at)-utcMillis(b.at))
}
export function assessExecution(snapshot: ExecutionSnapshot, timers: TimerHealth[], days: MarketDay[] | null, now: number, nextMaintenance: string | null = null): ExecutionStatus {
  const windows = days ? calendarWindows(days) : []
  const nextScan = windows.find(window => utcMillis(window.at) > now) ?? null
  const issues: string[] = []; let blocked = false; let unknown = false
  if (!snapshot.strategyId || !snapshot.strategyStatus) { unknown = true; issues.push('The configured strategy could not be verified.') }
  else if (snapshot.strategyStatus !== 'paper') { blocked = true; issues.push('The configured strategy is research-only; automatic paper orders are disabled.') }
  if (!snapshot.credentialsConfigured) { blocked = true; issues.push('Paper broker credentials are not configured.') }
  for (const timer of timers) {
    if (!timer.checked) { unknown = true; issues.push(`${timer.name}: service state could not be verified.`); continue }
    if (!timer.active) { blocked = true; issues.push(`${timer.name}: its timer is stopped.`) }
    if (timer.result !== 'success' || (timer.exitCode !== null && timer.exitCode !== 0)) issues.push(`${timer.name}: its last run failed.`)
    const maxAge = ['Worker', 'Exits'].includes(timer.name) ? 180000 : timer.name === 'Dispatcher' ? 600000 : null
    if (maxAge && (!Number.isFinite(utcMillis(timer.lastRun)) || now - utcMillis(timer.lastRun) > maxAge)) issues.push(`${timer.name}: no recent completed check.`)
  }
  if (!days || !nextScan) { unknown = true; issues.push('The next exchange session could not be verified.') }
  if (!snapshot.reconciliation) issues.push('Broker positions have not been reconciled yet.')
  else if (snapshot.reconciliation.status !== 'matched') { blocked = true; issues.push('Broker positions do not match the app’s records.') }
  else if (snapshot.lastSuccess && utcMillis(snapshot.reconciliation.at) < utcMillis(snapshot.lastSuccess.at)) issues.push('Broker reconciliation predates the last successful scan.')
  if (snapshot.latestScan?.status === 'failed') issues.push('The latest scan failed. Open Operations for the error.')
  const running = snapshot.latestScan?.status === 'running' || snapshot.latestScan?.status === 'queued'
  const lastDue = windows.filter(window => utcMillis(window.at) <= now && (!snapshot.strategySince || utcMillis(window.at) >= utcMillis(snapshot.strategySince))).at(-1)
  if (lastDue && now - utcMillis(lastDue.at) > 20 * 60000 &&
      (!snapshot.lastScheduledSuccess || utcMillis(snapshot.lastScheduledSuccess.at) < utcMillis(lastDue.at))) {
    issues.push(running ? 'A scheduled scan is taking longer than its 20-minute scheduling window.' : 'The most recent scheduled scan has not completed successfully.')
  }
  if (lastDue && now - utcMillis(lastDue.at) <= 20*60000 &&
      (!snapshot.lastScheduledSuccess || utcMillis(snapshot.lastScheduledSuccess.at) < utcMillis(lastDue.at)) && !running) {
    issues.push('A scan is due now; waiting for the dispatcher and worker.')
  }
  return { ...snapshot, generatedAt: new Date(now).toISOString(), nextScan, nextMaintenance,
    state: blocked ? 'blocked' : unknown ? 'unknown' : issues.length ? 'attention' : running ? 'running' : 'ready',
    issues, timers, calendarAvailable: days !== null }
}
