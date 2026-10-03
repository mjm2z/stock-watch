import { NextRequest, NextResponse } from 'next/server'
import { readLean, writeLean } from '@/lib/lean-store'
import { SystemsInputError } from '@/lib/systems-store'
import { authenticated, boundedBody, sameOrigin } from '@/lib/systems-auth'
export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export function GET() {
  try {
    return NextResponse.json(readLean(), { headers: { 'Cache-Control': 'no-store' } })
  } catch {
    return NextResponse.json(
      { error: 'LEAN validation storage is not installed.' },
      { status: 503 }
    )
  }
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request) || !authenticated(request))
    return NextResponse.json({ error: 'Operator access required.' }, { status: 403 })
  try {
    return NextResponse.json(writeLean(await boundedBody(request)))
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof SystemsInputError ? error.message : 'LEAN request could not be saved.',
      },
      { status: error instanceof SystemsInputError ? 400 : 503 }
    )
  }
}
