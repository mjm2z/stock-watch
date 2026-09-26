import { NextRequest, NextResponse } from 'next/server'
import { runDetail } from '@/lib/research-control'
export const dynamic = 'force-dynamic'
export async function GET(r: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params,
      full = r.nextUrl.searchParams.get('download') === '1'
    return NextResponse.json(runDetail(id, full), {
      headers: full
        ? { 'Content-Disposition': `attachment; filename="stockwatch-run-${id}.json"` }
        : {},
    })
  } catch {
    return NextResponse.json(
      { error: 'Run unavailable or evidence could not be verified.' },
      { status: 404 }
    )
  }
}
