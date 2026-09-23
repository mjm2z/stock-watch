jest.mock('next/server', () => ({ NextResponse: { json: (body: unknown) => body } }))
jest.mock('@/lib/worker-dashboard', () => ({ readDashboardOverview: jest.fn(), readDashboardOperations: jest.fn() }))
import { GET } from '@/app/api/health/route'
import { readDashboardOverview, readDashboardOperations } from '@/lib/worker-dashboard'

const now = new Date().toISOString()
const earlier = new Date(Date.now() - 3600000).toISOString()
const overview = { available: true, strategyStatus: 'paper', generatedAt: now,
  latestScan: { status: 'succeeded', scheduledFor: now }, metrics: { failedJobs: 25 } }
const reconciliation = { status: 'matched', capturedAt: now }

test('retains historical failure counts without declaring a repaired scan unhealthy', () => {
  (readDashboardOverview as jest.Mock).mockReturnValue(overview)
  ;(readDashboardOperations as jest.Mock).mockReturnValue({ brokerReconciliation: reconciliation, runs: [
    { id: 'old', command: 'work-once', status: 'failed', startedAt: earlier },
  ] })
  expect(GET()).toMatchObject({ status: 'ok', failedJobs: 25, recentOperationFailure: null })
})

test('a current failed scan remains degraded', () => {
  (readDashboardOverview as jest.Mock).mockReturnValue({ ...overview, latestScan: { status: 'failed', scheduledFor: now } })
  ;(readDashboardOperations as jest.Mock).mockReturnValue({ brokerReconciliation: reconciliation, runs: [] })
  expect(GET()).toMatchObject({ status: 'degraded' })
})

test('a later successful command resolves an earlier failure without hiding current failures', () => {
  (readDashboardOverview as jest.Mock).mockReturnValue(overview)
  ;(readDashboardOperations as jest.Mock).mockReturnValue({ brokerReconciliation: reconciliation, runs: [
    { id: 'fixed', command: 'refresh-fundamentals', status: 'succeeded', startedAt: now },
    { id: 'old', command: 'refresh-fundamentals', status: 'failed', startedAt: earlier },
  ] })
  expect(GET()).toMatchObject({ status: 'ok' })
  ;(readDashboardOperations as jest.Mock).mockReturnValue({ brokerReconciliation: reconciliation, runs: [
    { id: 'broken', command: 'refresh-fundamentals', status: 'failed', startedAt: now },
  ] })
  expect(GET()).toMatchObject({ status: 'degraded', recentOperationFailure: 'broken' })
})
