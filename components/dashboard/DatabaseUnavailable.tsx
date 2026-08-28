import { DatabaseZap } from 'lucide-react'

export function DatabaseUnavailable({ reason }: { reason?: string }) {
  return (
    <div className="rounded-xl border border-dashed bg-card p-8 text-center">
      <DatabaseZap className="mx-auto mb-4 h-10 w-10 text-muted-foreground" />
      <h2 className="text-lg font-semibold">Worker database is not connected</h2>
      <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
        {reason ?? 'Initialize the worker and configure STOCK_WATCH_DATABASE_PATH.'}
      </p>
      <code className="mt-4 inline-block rounded bg-muted px-3 py-2 text-xs">
        STOCK_WATCH_DATABASE_PATH=/var/lib/stock-watch/stock-watch.db
      </code>
    </div>
  )
}
