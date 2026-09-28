export const dynamic = 'force-dynamic'
export async function GET() {
  try {
    const response = await fetch('http://127.0.0.1:3012/health', {
      cache: 'no-store',
      signal: AbortSignal.timeout(1500),
    })
    return Response.json(await response.json(), { status: response.status })
  } catch {
    return Response.json({ healthy: false, error: 'Market collector unavailable' }, { status: 503 })
  }
}
