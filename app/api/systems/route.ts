import { NextRequest, NextResponse } from 'next/server'
import { readSystems, SystemsInputError, writeSystems } from '@/lib/systems-store'
import { authenticated, boundedBody, sameOrigin } from '@/lib/systems-auth'
export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
export async function GET(request: NextRequest) {
  try {
    return NextResponse.json(
      readSystems(request.nextUrl.searchParams.get('asset') === 'bitcoin' ? 'bitcoin' : 'stocks')
    )
  } catch {
    return NextResponse.json(
      {
        error:
          'Systems storage is unavailable. Install the systems migration and check worker health.',
      },
      { status: 503 }
    )
  }
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request) || !authenticated(request))
    return NextResponse.json({ error: 'Sign in as operator to change systems.' }, { status: 403 })
  let body: Record<string, unknown>
  try {
    body = await boundedBody(request)
  } catch {
    return NextResponse.json({ error: 'Invalid JSON request (maximum 12 KB).' }, { status: 400 })
  }
  try {
    return NextResponse.json(writeSystems(body))
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof SystemsInputError
            ? error.message
            : 'Could not save the change. Check migrations and worker health.',
      },
      { status: error instanceof SystemsInputError ? 400 : 503 }
    )
  }
}
