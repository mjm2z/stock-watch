import { NextRequest, NextResponse } from 'next/server'
import { accountPerformance } from '@/lib/performance-store'
export const dynamic = 'force-dynamic'
export function GET(request: NextRequest) {
  const asset = request.nextUrl.searchParams.get('asset') || 'stocks'
  if (!['stocks', 'bitcoin'].includes(asset))
    return NextResponse.json({ error: 'Choose stocks or bitcoin' }, { status: 400 })
  try {
    return NextResponse.json(accountPerformance(asset as 'stocks' | 'bitcoin'))
  } catch {
    return NextResponse.json(
      { available: false, reason: 'Account measurement unavailable' },
      { status: 503 }
    )
  }
}
