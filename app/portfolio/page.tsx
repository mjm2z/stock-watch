import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { PortfolioMetrics } from '@/components/PortfolioMetrics'
import { TradeTable } from '@/components/TradeTable'

export default function PortfolioPage() {
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
        <h1 className="text-3xl font-bold">Portfolio</h1>
        <p className="text-muted-foreground mt-1">
          Track your paper trades and real investments
        </p>
      </div>

      <div className="space-y-6">
        {/* Metrics */}
        <PortfolioMetrics />

        {/* Trade Table */}
        <TradeTable />
      </div>
    </main>
  )
}
