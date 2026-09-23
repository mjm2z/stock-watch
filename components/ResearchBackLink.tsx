'use client'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
export function ResearchBackLink() {
  const params = useSearchParams()
  const from = params.get('from')
  const allowed =
    from && /^\/(signals|research|portfolio|watchlist)(\?|$)/.test(from) ? from : '/research'
  return (
    <Link href={allowed} className="mb-6 inline-flex min-h-11 items-center text-sm underline">
      ← Back to{' '}
      {allowed.startsWith('/signals')
        ? 'signals'
        : allowed.startsWith('/portfolio')
          ? 'paper portfolio'
          : allowed.startsWith('/watchlist')
            ? 'watchlist'
            : 'research'}
    </Link>
  )
}
