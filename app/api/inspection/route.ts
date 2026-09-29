import { NextRequest, NextResponse } from 'next/server'
import { inspection } from '@/lib/inspection-store'
export const dynamic = 'force-dynamic'
export async function GET(request: NextRequest) {
  try {
    return NextResponse.json(inspection(request.nextUrl.searchParams), {
      headers: { 'Cache-Control': 'no-store' },
    })
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Inspection unavailable' },
      { status: 400 }
    )
  }
}
