import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { Watchlist } from '@/components/Watchlist'

export default function WatchlistPage() {
  return (
    <main className="container mx-auto p-4 sm:p-8">
      {/* Back link */}
      <Link
        href="/"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-6"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Search
      </Link>

      <div className="mb-6">
        <h1 className="text-3xl font-bold">Watchlist</h1>
        <p className="text-muted-foreground mt-1">
          Track your favorite stocks and monitor their performance
        </p>
      </div>

      <Watchlist />
    </main>
  )
}
