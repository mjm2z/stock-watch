import { NextResponse } from 'next/server'
import { readDashboardOperations, readDashboardOverview } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export function GET() {
  const overview = readDashboardOverview()
  if (!overview.available) {
    return NextResponse.json(
      { status: 'unavailable', reason: overview.unavailableReason },
      { status: 503 }
    )
  }
  const operations = readDashboardOperations(20)
  const reconciliation = operations.brokerReconciliation
  const recentFailure = operations.runs.find(
    run =>
      run.status === 'failed' &&
      Date.now() - new Date(run.startedAt).getTime() < 24 * 60 * 60 * 1000
  )
  const staleOperation = operations.runs.find(
    run =>
      run.status === 'running' &&
      Date.now() - new Date(run.heartbeatAt).getTime() > 20 * 60 * 1000
  )
  const brokerDegraded =
    overview.strategyStatus === 'paper' &&
    (reconciliation?.status !== 'matched' ||
      (overview.latestScan !== null &&
        new Date(reconciliation.capturedAt).getTime() <
          new Date(overview.latestScan.scheduledFor).getTime()))
  const degraded =
    overview.metrics.failedJobs > 0 ||
    overview.latestScan?.status === 'failed' ||
    recentFailure !== undefined ||
    staleOperation !== undefined ||
    brokerDegraded
  return NextResponse.json(
    {
      status: degraded ? 'degraded' : 'ok',
      generatedAt: overview.generatedAt,
      strategyStatus: overview.strategyStatus,
      latestScan: overview.latestScan?.scheduledFor ?? null,
      failedJobs: overview.metrics.failedJobs,
      brokerReconciliation: reconciliation?.status ?? null,
      recentOperationFailure: recentFailure?.id ?? null,
      staleOperation: staleOperation?.id ?? null,
    },
    { status: 200 }
  )
}
