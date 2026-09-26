import { NextResponse } from 'next/server'
import { readBitcoin } from '@/lib/systems-store'
export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'
export async function GET() {
  try {
    return NextResponse.json(readBitcoin())
  } catch {
    return NextResponse.json(
      { error: 'Bitcoin monitoring is not installed or its database is unavailable.' },
      { status: 503 }
    )
  }
}
