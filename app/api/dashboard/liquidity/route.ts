import { NextResponse } from 'next/server'
import { readLiquidityDiagnostics } from '@/lib/worker-dashboard'
export const dynamic='force-dynamic'
export const runtime='nodejs'
export function GET() {
  try { return NextResponse.json({diagnostics:readLiquidityDiagnostics()}) }
  catch { return NextResponse.json({error:'Liquidity diagnostics could not be loaded.'},{status:503}) }
}
