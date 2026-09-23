export default function Loading() {
  return (
    <main className="container mx-auto space-y-4 p-4 sm:p-8" aria-busy="true">
      <p role="status" className="text-sm text-muted-foreground">
        Loading dashboard…
      </p>
      <div className="h-20 animate-pulse rounded-xl bg-muted" />
      <div className="h-48 animate-pulse rounded-xl bg-muted" />
    </main>
  )
}
