import { NextRequest } from 'next/server'
import { authenticated, boundedBody, sameOrigin } from '@/lib/systems-auth'
export const dynamic = 'force-dynamic'
async function proxy(path: string, body?: Record<string, unknown>) {
  const token = process.env.STOCK_WATCH_BROWSER_SERVICE_TOKEN || ''
  if (token.length < 32)
    return Response.json(
      {
        manual: 'unconfigured',
        accounts: [],
        drafts: [],
        instructions: [],
        fills: [],
        error: 'Manual paper service credential is unconfigured.',
      },
      { status: body ? 503 : 200 }
    )
  try {
    const response = await fetch('http://127.0.0.1:3013' + path, {
      method: body ? 'POST' : 'GET',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(30000),
    })
    return Response.json(await response.json(), { status: response.status })
  } catch {
    return Response.json({ error: 'Manual paper service unavailable.' }, { status: 503 })
  }
}
export async function GET() {
  return proxy('/status')
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request) || !authenticated(request))
    return Response.json({ error: 'Operator sign-in required.' }, { status: 403 })
  try {
    const body = await boundedBody(request)
    if (!['preview', 'confirm'].includes(String(body.operation)))
      throw Error('Choose preview or confirm.')
    // Service accepts a separate explicit browser principal, never Telegram impersonation.
    return proxy('/' + body.operation, {
      ...body,
      user: 'browser-operator',
      chat: 'browser',
      source: 'browser',
    })
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : 'Invalid request' },
      { status: 400 }
    )
  }
}
