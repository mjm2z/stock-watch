import { NextRequest, NextResponse } from 'next/server'
import { readResearch, writeResearch, ResearchInputError } from '@/lib/research-store'
export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
export async function GET(request: NextRequest) {
  try { return NextResponse.json(readResearch(request.nextUrl.searchParams.get('symbol') || undefined)) }
  catch (error) { return NextResponse.json({ error: error instanceof ResearchInputError ? error.message : 'Shared research is unavailable. Check database migrations and service health.' }, { status: error instanceof ResearchInputError ? 400 : 503 }) }
}
export async function POST(request: NextRequest) {
  const origin = request.headers.get('origin')
  let sameOrigin = false
  try { sameOrigin = Boolean(origin && new URL(origin).host === request.headers.get('host')) } catch { /* Invalid origins are rejected. */ }
  if (!sameOrigin) return NextResponse.json({ error: 'Same-origin requests required.' }, { status: 403 })
  if (!request.headers.get('content-type')?.startsWith('application/json')) return NextResponse.json({ error: 'JSON required.' }, { status: 415 })
  // Bound the streamed body, including requests without Content-Length.
  const reader = request.body?.getReader()
  if (!reader) return NextResponse.json({ error: 'Request body required.' }, { status: 400 })
  const chunks: Uint8Array[] = []; let length = 0
  while (true) {
    const { done, value } = await reader.read(); if (done) break
    length += value.byteLength
    if (length > 20000) { await reader.cancel(); return NextResponse.json({ error: 'Request too large.' }, { status: 413 }) }
    chunks.push(value)
  }
  try {
    let body: unknown
    try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')) } catch { throw new ResearchInputError('Invalid JSON.') }
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new ResearchInputError('Object required.')
    writeResearch(body as Record<string, unknown>)
    return NextResponse.json({ ok: true })
  } catch (error) { return NextResponse.json({ error: error instanceof ResearchInputError ? error.message : 'Could not save research. Please retry.' }, { status: error instanceof ResearchInputError ? 400 : 503 }) }
}
