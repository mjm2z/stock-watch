import { NextRequest, NextResponse } from 'next/server'
import { researchDatabase } from '@/lib/research-store'
import { readFile, stat } from 'node:fs/promises'
import { createHash } from 'node:crypto'
export const dynamic = 'force-dynamic'
export async function GET(request: NextRequest) {
  const sha = request.nextUrl.searchParams.get('sha') || ''
  if (!/^[a-f0-9]{64}$/.test(sha))
    return NextResponse.json({ error: 'Invalid artifact identity' }, { status: 400 })
  try {
    const known = researchDatabase(false, (db) =>
      db
        .prepare(
          "SELECT 1 FROM research_previews WHERE json_extract(result_json,'$.artifact_sha256')=? LIMIT 1"
        )
        .get(sha)
    )
    if (!known) return NextResponse.json({ error: 'Artifact unavailable' }, { status: 404 })
    const path = process.env.STOCK_WATCH_DATABASE_PATH + '.systems-data/' + sha + '.preview.json'
    if ((await stat(path)).size > 64 * 1024 * 1024) throw Error('Artifact exceeds download limit')
    const raw = await readFile(path)
    if (createHash('sha256').update(raw).digest('hex') !== sha)
      throw Error('Artifact verification failed')
    return new Response(new Uint8Array(raw), {
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store',
        'Content-Disposition': `attachment; filename="preview-${sha.slice(0, 12)}.json"`,
      },
    })
  } catch {
    return NextResponse.json({ error: 'Verified full evidence is unavailable' }, { status: 503 })
  }
}
