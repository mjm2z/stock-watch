import { NextResponse } from 'next/server'
import { companyContext } from '@/lib/company-context'
import { ResearchInputError } from '@/lib/research-store'
export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
export async function GET(_request: Request, { params }: { params: Promise<{ ticker: string }> }) {
  try {
    return NextResponse.json(companyContext((await params).ticker), {
      headers: { 'Cache-Control': 'no-store' },
    })
  } catch (error) {
    return NextResponse.json(
      {
        error:
          error instanceof ResearchInputError
            ? error.message
            : 'Company information is temporarily unavailable.',
      },
      {
        status: error instanceof ResearchInputError ? 400 : 503,
        headers: { 'Cache-Control': 'no-store' },
      }
    )
  }
}
