'use client'
export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <main className="container mx-auto space-y-4 p-4 sm:p-8">
      <h1 className="text-2xl font-semibold">This view could not load</h1>
      <p role="alert" className="text-muted-foreground">
        An unexpected error interrupted the page. Your saved trading and research records have not
        been changed.
      </p>
      <button className="min-h-11 rounded-md border px-4" onClick={reset}>
        Try again
      </button>
      <a className="ml-4 underline" href="/operations">
        Review operations
      </a>
    </main>
  )
}
