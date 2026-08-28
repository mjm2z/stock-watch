import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { SignalTable } from '@/components/dashboard/SignalTable'
import {
  readDashboardSignals,
  WorkerDatabaseUnavailable,
} from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'

type SignalSearchParams = {
  decision?: string
  horizon?: string
  minimumScore?: string
}

export default async function SignalsPage({
  searchParams,
}: {
  searchParams: Promise<SignalSearchParams>
}) {
  const resolvedSearchParams = await searchParams
  const filters = {
    decision: resolvedSearchParams.decision || undefined,
    horizon: optionalNumber(resolvedSearchParams.horizon),
    minimumScore: optionalNumber(resolvedSearchParams.minimumScore),
    limit: 250,
  }
  try {
    const signals = readDashboardSignals(filters)
    return (
      <main className="container mx-auto space-y-6 p-4 sm:p-8">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Signal ledger</h1>
          <p className="mt-2 text-muted-foreground">
            Every scored horizon is retained, including rejections and incomplete observations.
          </p>
        </div>
        <form className="grid gap-3 rounded-xl border bg-card p-4 sm:grid-cols-4">
          <select name="decision" defaultValue={resolvedSearchParams.decision ?? ''} className="rounded-md border bg-background px-3 py-2 text-sm">
            <option value="">All decisions</option>
            <option value="qualified">Qualified</option>
            <option value="rejected">Rejected</option>
          </select>
          <select name="horizon" defaultValue={resolvedSearchParams.horizon ?? ''} className="rounded-md border bg-background px-3 py-2 text-sm">
            <option value="">All horizons</option>
            {[5, 21, 63, 105].map(value => <option key={value} value={value}>{value} trading days</option>)}
          </select>
          <input
            name="minimumScore"
            type="number"
            min="0"
            max="100"
            step="1"
            defaultValue={resolvedSearchParams.minimumScore}
            placeholder="Minimum score"
            className="rounded-md border bg-background px-3 py-2 text-sm"
          />
          <button className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">
            Apply filters
          </button>
        </form>
        <div className="text-sm text-muted-foreground">{signals.length} observations</div>
        <SignalTable signals={signals} />
      </main>
    )
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) {
      return <main className="container mx-auto p-4 sm:p-8"><DatabaseUnavailable reason={error.message} /></main>
    }
    throw error
  }
}

function optionalNumber(value?: string): number | undefined {
  if (!value) return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}
