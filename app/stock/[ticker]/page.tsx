import { Suspense } from 'react'
import { ResearchBackLink } from '@/components/ResearchBackLink'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { StockQuote } from '@/components/StockQuote'
import { StockChart } from '@/components/StockChart'
import { StockAnalysis } from '@/components/StockAnalysis'
import { aiAnalysisEnabled } from '@/lib/server-features'
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
      <Suspense fallback={<Link href="/research">Back to research</Link>}>
        <ResearchBackLink />
      </Suspense>

      <div className="space-y-6">
        {/* Quote and key metrics */}
        <StockQuote ticker={upperTicker} />

        {/* Price chart */}
        <StockChart ticker={upperTicker} />

        {aiAnalysisEnabled() ? <StockAnalysis ticker={upperTicker} /> : null}

        {/* Quick actions */}
        <QuickActions ticker={upperTicker} />
      </div>
    </main>
  )
}
