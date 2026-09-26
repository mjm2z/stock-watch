import { NextRequest, NextResponse } from 'next/server'
import { controlOverview, controlCommand } from '@/lib/research-control'
import { assetOf } from '@/lib/workspace-store'
import { authenticated, sameOrigin, boundedBody } from '@/lib/systems-auth'
import { SystemsInputError } from '@/lib/systems-store'
export const dynamic = 'force-dynamic'
export function GET(r: NextRequest) {
  try {
    return NextResponse.json(
      controlOverview(assetOf(r.nextUrl.searchParams.get('asset') || 'stocks'))
    )
  } catch {
    return NextResponse.json(
      { error: 'Research controls unavailable. Check migration and worker health.' },
      { status: 503 }
    )
  }
}
export async function POST(r: NextRequest) {
  if (!sameOrigin(r) || !authenticated(r))
    return NextResponse.json({ error: 'Sign in as operator.' }, { status: 403 })
  try {
    return NextResponse.json(controlCommand(await boundedBody(r)))
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof SystemsInputError ? e.message : 'Command unavailable' },
      { status: e instanceof SystemsInputError ? 400 : 503 }
    )
  }
}
