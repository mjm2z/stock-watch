import Link from 'next/link'
export function DatabaseUnavailable({ reason }: { reason?: string }) {
  return (
    <section className="space-y-3 rounded-xl border border-dashed bg-card p-6" role="status">
      <h2 className="text-lg font-semibold">Trading data is unavailable</h2>
      <p className="text-sm text-muted-foreground">
        This view could not read the worker database. Existing trades are preserved; this page
        cannot confirm their current status.
      </p>
      <Link href="/operations" className="inline-block py-2 text-sm underline">
        Review operations
      </Link>
      <details className="text-sm">
        <summary>Connection details</summary>
        <p className="mt-2 break-all text-muted-foreground">
          {reason ?? 'The worker database path has not been configured.'}
        </p>
      </details>
    </section>
  )
}
