import { NextRequest, NextResponse } from 'next/server'
import { scanDiagnostics } from '@/lib/scan-diagnostics'
export const dynamic = 'force-dynamic'
export function GET(request: NextRequest) {
  try {
    return NextResponse.json({
      diagnostics: scanDiagnostics(request.nextUrl.searchParams.get('id') || undefined),
    })
  } catch {
    return NextResponse.json({ error: 'Scan diagnostics unavailable' }, { status: 503 })
  }
}
