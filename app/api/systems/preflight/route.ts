import { NextRequest, NextResponse } from 'next/server'
import { researchDatabase } from '@/lib/research-store'
import { stockPrerequisites } from '@/lib/stock-prerequisites'
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
    return NextResponse.json(
      researchDatabase(false, (db) =>
        stockPrerequisites(db, new Date(start).toISOString(), new Date(end).toISOString())
      )
    )
  } catch {
    return NextResponse.json(
      { error: 'Stock data prerequisites are unavailable. Check database readiness.' },
      { status: 503 }
    )
  }
}
