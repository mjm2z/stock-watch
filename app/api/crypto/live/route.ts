export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
export async function GET(request: Request) {
  const stream = new URL(request.url).searchParams.get('stream') === '1'
  const controller = new AbortController()
  request.signal.addEventListener('abort', () => controller.abort(), { once: true })
  const timeout = setTimeout(() => controller.abort(), 3000)
  try {
    const upstream = await fetch(`http://127.0.0.1:3012/${stream ? 'events' : 'snapshot'}`, {
      signal: controller.signal,
      cache: 'no-store',
    })
    clearTimeout(timeout)
    if (!upstream.ok || !upstream.body) throw new Error('Feed unavailable')
    return new Response(upstream.body, {
      headers: {
        'Content-Type': stream ? 'text/event-stream' : 'application/json',
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',
      },
    })
  } catch {
    return Response.json(
      {
        source: 'Coinbase Advanced Trade ticker',
        price: null,
        fresh: false,
        status: 'Reconnecting',
      },
      { status: 503 }
    )
  } finally {
    clearTimeout(timeout)
  }
}
