import { NextResponse } from 'next/server'
import { dataCapabilities } from '@/lib/data-capabilities'
export const dynamic = 'force-dynamic'
export function GET() {
  try {
    return NextResponse.json(dataCapabilities())
  } catch {
    return NextResponse.json({ error: 'Data capability report unavailable' }, { status: 503 })
  }
}
