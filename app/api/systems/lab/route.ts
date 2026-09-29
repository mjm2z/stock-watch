import { NextRequest, NextResponse } from 'next/server'
import { readLab, labCommand } from '@/lib/research-lab'
import { authenticated, sameOrigin, boundedBody } from '@/lib/systems-auth'
import { SystemsInputError } from '@/lib/systems-store'
export const dynamic = 'force-dynamic'
export async function GET(r: NextRequest) {
  try {
    return NextResponse.json(
      readLab(r.nextUrl.searchParams.get('asset') === 'bitcoin' ? 'bitcoin' : 'stocks'),
      { headers: { 'Cache-Control': 'no-store' } }
    )
  } catch {
    return NextResponse.json(
      { error: 'Research inspection unavailable; migration or worker setup may be pending' },
      { status: 503 }
    )
  }
}
export async function POST(r: NextRequest) {
  if (!sameOrigin(r) || !authenticated(r))
    return NextResponse.json({ error: 'Sign in as operator to save research' }, { status: 403 })
  try {
    return NextResponse.json(labCommand(await boundedBody(r)))
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof SystemsInputError ? e.message : 'Research request unavailable' },
      { status: e instanceof SystemsInputError ? 400 : 503 }
    )
  }
}
