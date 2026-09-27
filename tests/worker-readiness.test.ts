import { assessDiscovery, Schedule } from '@/lib/worker-readiness'
const now = Date.parse('2026-09-27T02:00:00Z')
const schedule: Schedule = {
  active: true,
  nextAt: '2026-09-27T07:00:00Z',
  lastAt: null,
  failed: false,
}
const input = { enabled: true, schedule, pending: 0, blocked: 0, running: 0 }
test('only a verified future first schedule gets a healthy not-yet-due state', () => {
  expect(assessDiscovery(input, now)).toMatchObject({ state: 'not_yet_due', healthy: true })
  expect(assessDiscovery({ ...input, schedule: null }, now).healthy).toBe(false)
  expect(
    assessDiscovery({ ...input, schedule: { ...schedule, lastAt: '2026-09-26T07:00:00Z' } }, now)
      .healthy
  ).toBe(false)
  expect(assessDiscovery(input, Date.parse('2026-09-28T07:00:00Z')).healthy).toBe(false)
})
test('disabled timer, failed service, stale heartbeat and blocked prerequisites stay distinct', () => {
  expect(assessDiscovery({ ...input, schedule: { ...schedule, active: false } }, now).state).toBe(
    'disabled'
  )
  expect(assessDiscovery({ ...input, schedule: { ...schedule, failed: true } }, now).state).toBe(
    'failed'
  )
  expect(assessDiscovery({ ...input, heartbeat: { at: '2026-09-25T00:00:00Z' } }, now).state).toBe(
    'stale'
  )
  expect(
    assessDiscovery({ ...input, heartbeat: { at: new Date(now).toISOString() }, blocked: 2 }, now)
  ).toMatchObject({ state: 'blocked', healthy: false })
  expect(assessDiscovery({ ...input, enabled: false }, now)).toMatchObject({
    state: 'disabled',
    healthy: true,
  })
})
test('checkpointed trials wait in the queue when the service is not running', () => {
  const heartbeat = { at: new Date(now).toISOString() }
  expect(assessDiscovery({ ...input, heartbeat, running: 1 }, now).state).toBe('queued')
  expect(assessDiscovery({ ...input, heartbeat, running: 1, schedule: { ...schedule, running: true } }, now).state).toBe('running')
})
