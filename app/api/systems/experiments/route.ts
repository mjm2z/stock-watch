import { NextRequest, NextResponse } from 'next/server'
import { authenticated, sameOrigin, boundedBody } from '@/lib/systems-auth'
import {
  experimentAsset,
  readExperiments,
  experimentDetail,
  decisionEvidence,
  experimentCommand,
  ExperimentInputError,
} from '@/lib/experiment-store'
export const dynamic = 'force-dynamic'
function failure(error: unknown) {
  return NextResponse.json(
    {
      error:
        error instanceof ExperimentInputError
          ? error.message
          : 'Experiments unavailable. Check migrations and worker health.',
    },
    { status: error instanceof ExperimentInputError ? 400 : 503 }
  )
}
export async function GET(request: NextRequest) {
  try {
    const query = request.nextUrl.searchParams,
      asset = experimentAsset(query.get('asset') || 'stocks')
    return NextResponse.json(
      query.has('decision')
        ? decisionEvidence(asset, query.get('decision')!)
        : query.has('instance')
          ? experimentDetail(asset, query.get('instance')!, query.get('before') || undefined)
          : readExperiments(asset)
    )
  } catch (error) {
    return failure(error)
  }
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request) || !authenticated(request))
    return NextResponse.json(
      { error: 'An operator session from this origin is required.' },
      { status: 403 }
    )
  let body: Record<string, unknown>
  try {
    body = await boundedBody(request)
  } catch {
    return NextResponse.json(
      { error: 'A JSON object of at most 12 KB is required.' },
      { status: 400 }
    )
  }
  try {
    return NextResponse.json(experimentCommand(body), { status: 202 })
  } catch (error) {
    return failure(error)
  }
}
