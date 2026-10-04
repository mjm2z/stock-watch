import { NextResponse } from 'next/server'
import { macroContext } from '@/lib/macro-context'
export const dynamic = 'force-dynamic'
export async function GET() {
  return NextResponse.json(await macroContext(), { headers: { 'Cache-Control': 'no-store' } })
}
