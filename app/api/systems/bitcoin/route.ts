import { NextRequest, NextResponse } from 'next/server'
import { readBitcoinAutomation, writeBitcoinAutomation } from '@/lib/bitcoin-automation-store'
import { SystemsInputError } from '@/lib/systems-store'
import { authenticated, boundedBody, sameOrigin } from '@/lib/systems-auth'
export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
export async function GET() {
  try {
    return NextResponse.json(readBitcoinAutomation())
  } catch {
    return NextResponse.json(
      {
        error:
          'Bitcoin automation storage is unavailable. Install migration 017 and check worker health.',
      },
      { status: 503 }
    )
  }
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request) || !authenticated(request))
    return NextResponse.json(
      { error: 'Sign in as operator to change automation.' },
      { status: 403 }
    )
  let body: Record<string, unknown>
  try {
    body = await boundedBody(request)
  } catch {
    return NextResponse.json({ error: 'Invalid JSON request (maximum 12 KB).' }, { status: 400 })
  }
  try {
    return NextResponse.json(writeBitcoinAutomation(body))
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof SystemsInputError
            ? error.message
            : 'Could not save this change. Check worker health.',
      },
      { status: error instanceof SystemsInputError ? 400 : 503 }
    )
  }
}
