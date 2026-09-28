import { NextRequest, NextResponse } from 'next/server'
import { stockPreflight } from '@/lib/stock-preflight-cache'
export const dynamic = 'force-dynamic'

export function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams
  const start = Date.parse(params.get('start') || '')
  const end = Date.parse(params.get('end') || '')
  if (
    params.get('asset') !== 'stocks' ||
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    start >= end ||
    start < Date.UTC(2016, 0, 1) ||
    end > Date.now()
  )
    return NextResponse.json(
      { error: 'Choose a stock historical interval since 2016.' },
      { status: 400 }
    )
  try {
    const report = stockPreflight(new Date(start).toISOString(), new Date(end).toISOString())
    return NextResponse.json(report, {
      status: report.state === 'unavailable' ? 503 : report.state === 'ready' ? 200 : 202,
    })
  } catch {
    return NextResponse.json(
      { error: 'Stock data prerequisites are unavailable. Check database readiness.' },
      { status: 503 }
    )
  }
}
