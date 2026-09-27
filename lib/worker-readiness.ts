import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

export type Schedule = {
  active: boolean
  nextAt: string | null
  lastAt: string | null
  failed: boolean
  running?: boolean
}
export type WorkerState =
  | 'not_yet_due'
  | 'running'
  | 'queued'
  | 'blocked'
  | 'failed'
  | 'stale'
  | 'disabled'
  | 'healthy'
  | 'unknown'
const execute = promisify(execFile)
export async function discoverySchedule(): Promise<Schedule | null> {
  try {
    const { stdout } = await execute(
      'systemctl',
      [
        'show',
        'stock-watch-discovery.timer',
        'stock-watch-discovery.service',
        '--property=Id,ActiveState,NextElapseUSecRealtime,LastTriggerUSec,Result',
      ],
      { timeout: 1500, maxBuffer: 8192, env: { ...process.env, TZ: 'UTC', LC_ALL: 'C' } }
    )
    const blocks = stdout
      .trim()
      .split(/\n\n+/)
      .map((block) =>
        Object.fromEntries(
          block.split('\n').map((line) => {
            const at = line.indexOf('=')
            return [line.slice(0, at), line.slice(at + 1)]
          })
        )
      )
    const timer = blocks.find((b) => b.Id === 'stock-watch-discovery.timer')
    const service = blocks.find((b) => b.Id === 'stock-watch-discovery.service')
    if (!timer) return null
    const date = (value?: string) =>
      value && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString() : null
    return {
      active: timer.ActiveState === 'active',
      nextAt: date(timer.NextElapseUSecRealtime),
      lastAt: date(timer.LastTriggerUSec),
      running: service?.ActiveState === 'active' || service?.ActiveState === 'activating',
      failed:
        service?.ActiveState === 'failed' || (!!service?.Result && service.Result !== 'success'),
    }
  } catch {
    return null
  }
}

export function assessDiscovery(
  input: {
    enabled: boolean
    heartbeat?: { at: string; error?: unknown }
    schedule: Schedule | null
    pending: number
    blocked: number
    running: number
  },
  now = Date.now()
) {
  const { schedule, heartbeat } = input
  const age = heartbeat ? (now - Date.parse(heartbeat.at)) / 1000 : null
  let state: WorkerState
  if (!input.enabled) state = 'disabled'
  else if (schedule && !schedule.active) state = 'disabled'
  else if (schedule?.failed) state = 'failed'
  else if (heartbeat?.error) state = 'failed'
  else if (heartbeat && (age === null || !Number.isFinite(age) || age < 0 || age > 27 * 3600))
    state = 'stale'
  else if (heartbeat)
    state =
      input.running && schedule?.running
        ? 'running'
        : input.pending || input.running
          ? 'queued'
          : input.blocked && !input.pending
            ? 'blocked'
            : 'healthy'
  else if (
    schedule?.active &&
    !schedule.lastAt &&
    schedule.nextAt &&
    Date.parse(schedule.nextAt) > now
  )
    state = 'not_yet_due'
  else state = schedule ? 'stale' : 'unknown'
  const healthy =
    ['healthy', 'running', 'queued', 'not_yet_due'].includes(state) ||
    (!input.enabled && state === 'disabled')
  return {
    worker: 'discovery',
    state,
    healthy,
    ageSeconds: age,
    maxAgeSeconds: 27 * 3600,
    nextAt: schedule?.nextAt ?? null,
    queued: input.pending,
    blocked: input.blocked,
    error: healthy
      ? null
      : heartbeat?.error ||
        (state === 'blocked' ? 'Research prerequisites need review' : `Discovery ${state}`),
  }
}
