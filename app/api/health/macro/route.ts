import { NextResponse } from 'next/server'
import { macroContext } from '@/lib/macro-context'
export const dynamic = 'force-dynamic'
export async function GET() {
  const state = await macroContext(true)
  return NextResponse.json(state, {
    status: state.healthy ? 200 : 503,
    headers: { 'Cache-Control': 'no-store' },
  })
}
