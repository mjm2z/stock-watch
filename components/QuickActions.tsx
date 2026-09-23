import Link from 'next/link'
import { WatchlistButton } from '@/components/WatchlistButton'

export function QuickActions({ ticker }: { ticker: string }) {
  return <section className="rounded-lg border bg-card p-6">
    <h2 className="mb-4 text-lg font-semibold">Research & paper execution</h2>
    <div className="flex flex-wrap items-center gap-4">
      <WatchlistButton ticker={ticker} />
      <Link className="text-primary underline" href={`/signals?symbol=${encodeURIComponent(ticker)}`}>Decision history</Link>
      <Link className="text-primary underline" href="/portfolio">Broker paper portfolio</Link>
      <Link className="text-primary underline" href={`/research?symbol=${encodeURIComponent(ticker)}`}>Research journal</Link>
    </div>
    <p className="mt-3 text-sm text-muted-foreground">Orders are submitted by the scheduled paper strategy after its checks pass. Adding research or a watchlist item does not submit an order.</p>
  </section>
}
