import { NextRequest, NextResponse } from 'next/server'
import { chartRequest } from '@/lib/workspace-store'
import { SystemsInputError } from '@/lib/systems-store'
export const dynamic = 'force-dynamic'
export async function GET(r: NextRequest) {
  try {
    const p = r.nextUrl.searchParams
    return NextResponse.json(chartRequest(p.get('range') || '1M', p.get('start'), p.get('end')))
  } catch (e) {
    return NextResponse.json(
      {
        error:
          e instanceof SystemsInputError
            ? e.message
            : 'Chart data is unavailable. Check the history worker.',
      },
      { status: e instanceof SystemsInputError ? 400 : 503 }
    )
  }
}
