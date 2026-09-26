import { NextRequest, NextResponse } from 'next/server'
import { readWorkspace, assetOf } from '@/lib/workspace-store'
export const dynamic = 'force-dynamic'
export async function GET(r: NextRequest) {
  try {
    return NextResponse.json(
      readWorkspace(assetOf(r.nextUrl.searchParams.get('asset') || 'stocks'))
    )
  } catch {
    return NextResponse.json(
      { error: 'The workspace is unavailable. Check migrations and worker health.' },
      { status: 503 }
    )
  }
}
