import { NextResponse } from 'next/server'
import { evaluationDetail } from '@/lib/research-control'
export const dynamic = 'force-dynamic'
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params
    return NextResponse.json(evaluationDetail(id), {
      headers: { 'Content-Disposition': `attachment; filename="stockwatch-evaluation-${id}.json"` },
    })
  } catch {
    return NextResponse.json({ error: 'Evaluation unavailable' }, { status: 404 })
  }
}
