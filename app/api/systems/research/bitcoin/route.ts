import evidence from '@/lib/research/bitcoin-study-evidence.json'
export function GET() {
  return Response.json(evidence, {
    headers: {
      'Content-Disposition': 'attachment; filename="stockwatch-bitcoin-study-2026-09-26.json"',
      'Cache-Control': 'public, max-age=3600',
    },
  })
}
