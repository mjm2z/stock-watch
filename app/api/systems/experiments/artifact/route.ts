import { NextRequest, NextResponse } from 'next/server'
import { researchDatabase } from '@/lib/research-store'
import { createReadStream } from 'node:fs'
import { lstat } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { Readable } from 'node:stream'
export const dynamic = 'force-dynamic'
export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get('job') || '',
    kind = request.nextUrl.searchParams.get('kind') || 'summary'
  if (!/^[a-zA-Z0-9_-]{8,100}$/.test(id) || !['summary', 'evidence', 'replay'].includes(kind))
    return NextResponse.json({ error: 'Invalid replay artifact.' }, { status: 400 })
  try {
    const row = researchDatabase(false, (db) =>
      db
        .prepare(
          "SELECT result_json FROM workspace_jobs WHERE id=? AND kind='experiment_replay' AND status='succeeded'"
        )
        .get(id)
    )
    if (!row) return NextResponse.json({ error: 'Completed replay not found.' }, { status: 404 })
    const result = JSON.parse(String(row.result_json)),
      name =
        kind === 'summary'
          ? result.artifact_sha256 + '.experiment-replay.json'
          : result.artifacts?.[kind]
    if (
      typeof name !== 'string' ||
      !/^[a-f0-9]{64}\.experiment-(replay|evidence)\.(json|db)$/.test(name)
    )
      throw Error('Unknown artifact')
    const path = process.env.STOCK_WATCH_DATABASE_PATH + '.systems-data/' + name,
      info = await lstat(path)
    if (!info.isFile() || info.size > 1024 * 1024 * 1024)
      throw Error('Artifact unavailable or exceeds one GB')
    const hash = createHash('sha256')
    for await (const chunk of createReadStream(path)) hash.update(chunk)
    if (hash.digest('hex') !== name.slice(0, 64)) throw Error('Artifact verification failed')
    return new Response(Readable.toWeb(createReadStream(path)) as ReadableStream<Uint8Array>, {
      headers: {
        'Content-Type': kind === 'summary' ? 'application/json' : 'application/vnd.sqlite3',
        'Content-Length': String(info.size),
        'Cache-Control': 'no-store',
        'Content-Disposition': `attachment; filename="${name}"`,
      },
    })
  } catch {
    return NextResponse.json({ error: 'Verified replay evidence is unavailable.' }, { status: 503 })
  }
}
