import { NextRequest, NextResponse } from 'next/server'
import { authenticated, sameOrigin, boundedBody } from '@/lib/systems-auth'
import { workspaceCommand } from '@/lib/workspace-store'
import { SystemsInputError } from '@/lib/systems-store'
export async function POST(r: NextRequest) {
  if (!sameOrigin(r) || !authenticated(r))
    return NextResponse.json({ error: 'Sign in as operator to make changes.' }, { status: 403 })
  try {
    return NextResponse.json(workspaceCommand(await boundedBody(r)))
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof SystemsInputError ? e.message : 'The command could not be saved.' },
      { status: e instanceof SystemsInputError ? 400 : 503 }
    )
  }
}
