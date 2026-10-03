import { NextRequest, NextResponse } from 'next/server'
import { researchDatabase } from '@/lib/research-store'
import { readFile, stat } from 'node:fs/promises'
import { createReadStream } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { Readable } from 'node:stream'
export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!/^[0-9a-f]{8}-[0-9a-f-]{27}$/.test(id))
    return NextResponse.json({ error: 'Invalid comparison' }, { status: 400 })
  try {
    const row = researchDatabase(false, (db) =>
      db.prepare('SELECT status,summary_json,result_path FROM lean_comparisons WHERE id=?').get(id)
    )
    if (!row) return NextResponse.json({ error: 'Comparison not found' }, { status: 404 })
    if (!request.nextUrl.searchParams.has('page') && !request.nextUrl.searchParams.has('download'))
      return NextResponse.json({
        status: row.status,
        summary: row.summary_json ? JSON.parse(String(row.summary_json)) : null,
        artifactsAvailable: Boolean(row.result_path),
      })
    if (!row.result_path)
      return NextResponse.json(
        { error: 'Detailed artifacts are unavailable or expired; summary is retained.' },
        { status: 410 }
      )
    const root = resolve(`${process.env.STOCK_WATCH_DATABASE_PATH}.lean-data`, id)
    const path = resolve(String(row.result_path))
    if (dirname(path) !== root) throw Error('Invalid artifact path')
    if (request.nextUrl.searchParams.has('download')) {
      if ((await stat(path)).size > 128 * 1024 * 1024) throw Error('Oversized artifact')
      return new Response(Readable.toWeb(createReadStream(path)) as ReadableStream, {
        headers: {
          'Content-Type': 'application/json',
          'Content-Disposition': `attachment; filename="lean-${id}.json"`,
          'Cache-Control': 'no-store',
        },
      })
    }
    const page = Number(request.nextUrl.searchParams.get('page'))
    if (!Number.isInteger(page) || page < 0 || page > 99)
      return NextResponse.json({ error: 'Invalid page' }, { status: 400 })
    const file = join(root, `differences-${page}.json`)
    if ((await stat(file)).size > 1048576) throw Error('Oversized page')
    return NextResponse.json({ differences: JSON.parse(await readFile(file, 'utf8')) })
  } catch {
    return NextResponse.json({ error: 'Comparison evidence is unavailable.' }, { status: 503 })
  }
}
