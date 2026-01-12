import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { StockQuote } from '@/components/StockQuote'
import { StockChart } from '@/components/StockChart'
import { StockAnalysis } from '@/components/StockAnalysis'
import { QuickActions } from '@/components/QuickActions'

interface StockPageProps {
  params: Promise<{
    ticker: string
  }>
}

export default async function StockPage({ params }: StockPageProps) {
  const { ticker } = await params
  const upperTicker = ticker.toUpperCase()

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

      <div className="space-y-6">
        {/* Quote and key metrics */}
        <StockQuote ticker={upperTicker} />

        {/* Price chart */}
        <StockChart ticker={upperTicker} />

        {/* AI Analysis */}
        <StockAnalysis ticker={upperTicker} />

        {/* Quick actions */}
        <QuickActions ticker={upperTicker} />
      </div>
    </main>
  )
}
