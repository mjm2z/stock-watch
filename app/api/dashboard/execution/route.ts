import { NextResponse } from 'next/server'
import { readExecutionStatus } from '@/lib/execution-status'
export const dynamic='force-dynamic'
export const runtime='nodejs'
export async function GET() {
  try { return NextResponse.json(await readExecutionStatus(),{headers:{'Cache-Control':'no-store'}}) }
  catch { return NextResponse.json({error:'Execution status could not be checked. See Operations for service details.'},{status:503}) }
}
