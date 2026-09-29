import { NextRequest, NextResponse } from 'next/server'
import { activity } from '@/lib/inspection-store'
export const dynamic = 'force-dynamic'
export async function GET(request: NextRequest) {
  try {
    return NextResponse.json(activity(request.nextUrl.searchParams), {
      headers: { 'Cache-Control': 'no-store' },
    })
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Activity unavailable' },
      { status: 400 }
    )
  }
}
