import { NextRequest, NextResponse } from 'next/server'
import {
  readDashboardSignals,
  readSignalSummary,
  WorkerDatabaseUnavailable,
} from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams
  try {
    const filters = {
      scanRunId: params.get('scanRunId') || undefined,
      timezone: params.get('timezone') || undefined,
      symbol: params.get('symbol') || undefined,
      strategyId: params.get('strategyId') || undefined,
      since: params.get('since') || undefined,
      until: params.get('until') || undefined,
      reason: params.get('reason') || undefined,
      offset: params.get('format') === 'csv' ? 0 : optionalNumber(params.get('offset')),
      decision: params.get('decision') || undefined,
      horizon: optionalNumber(params.get('horizon')),
      minimumScore: optionalNumber(params.get('minimumScore')),
      limit: optionalNumber(params.get('limit')),
    }
    const signals = readDashboardSignals(filters)
    const summary = readSignalSummary(filters)
    if (params.get('format') === 'csv') {
      const cell = (value: unknown) => {
        let text = value == null ? '' : String(value)
        if (/^[=+@\-\t\r\n]/.test(text)) text = "'" + text
        return '"' + text.replaceAll('"', '""') + '"'
      }
      const rows = [
        [
          'Ticker',
          'As of (UTC)',
          'Strategy',
          'Horizon',
          'Rank score',
          'Decision',
          'Reasons',
          'Order status',
          'Evaluation',
          'Modeled net return',
        ],
        ...signals.map((s) => [
          s.symbol,
          s.asOf,
          s.strategyId,
          s.horizonTradingDays,
          s.score,
          s.decision,
          s.reasons.join('; '),
          s.orderStatus,
          s.evaluationState,
          s.netReturn,
        ]),
      ]
      return new NextResponse(rows.map((row) => row.map(cell).join(',')).join('\r\n'), {
        headers: {
          'X-Total-Count': String(summary.total),
          'X-Export-Truncated': String(summary.total > signals.length),
          'Content-Type': 'text/csv; charset=utf-8',
          'Content-Disposition': 'attachment; filename="stock-watch-decisions.csv"',
        },
      })
    }
    return NextResponse.json({ signals, meta: summary })
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) {
      return NextResponse.json({ signals: [], error: error.message }, { status: 503 })
    }
    if (error instanceof Error && error.message.includes('calendar date'))
      return NextResponse.json({ error: error.message }, { status: 400 })
    throw error
  }
}

function optionalNumber(value: string | null): number | undefined {
  if (value === null || value.trim() === '') return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}
