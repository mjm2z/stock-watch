import { NextResponse } from 'next/server'
import { filingDetails } from '@/lib/filing-details'
import { ResearchInputError } from '@/lib/research-store'
export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ ticker: string; accession: string }> }
) {
  try {
    return NextResponse.json(filingDetails((await params).ticker, (await params).accession), {
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
