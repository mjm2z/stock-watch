import { NextRequest, NextResponse } from 'next/server'
import { authenticated, boundedBody, cookieName, login, sameOrigin } from '@/lib/systems-auth'
export const dynamic = 'force-dynamic'
export async function GET(request: NextRequest) {
  return NextResponse.json({
    authenticated: authenticated(request),
    configured: Boolean(
      process.env.SYSTEMS_OPERATOR_TOKEN && process.env.SYSTEMS_OPERATOR_TOKEN.length >= 32
    ),
  })
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request))
    return NextResponse.json({ error: 'Same-origin requests required.' }, { status: 403 })
  try {
    const body = await boundedBody(request)
    const token = login(body.token)
    if (!token)
      return NextResponse.json(
        { error: 'Invalid operator token or operator access is not configured.' },
        { status: 403 }
      )
    const response = NextResponse.json({ authenticated: true })
    response.cookies.set(cookieName, token, {
      httpOnly: true,
      sameSite: 'strict',
      secure: request.nextUrl.protocol === 'https:',
      path: '/api/systems',
      maxAge: 3600,
    })
    return response
  } catch {
    return NextResponse.json({ error: 'Invalid request.' }, { status: 400 })
  }
}
export async function DELETE(request: NextRequest) {
  if (!sameOrigin(request))
    return NextResponse.json({ error: 'Same-origin requests required.' }, { status: 403 })
  const response = NextResponse.json({ authenticated: false })
  response.cookies.set(cookieName, '', { path: '/api/systems', maxAge: 0 })
  return response
}
