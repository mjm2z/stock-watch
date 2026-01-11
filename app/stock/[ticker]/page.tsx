interface StockPageProps {
  params: Promise<{
    ticker: string
  }>
}

export default async function StockPage({ params }: StockPageProps) {
  const { ticker } = await params

  return (
    <main className="container mx-auto p-8">
      <div className="space-y-6">
        <h1 className="text-3xl font-bold">{ticker.toUpperCase()}</h1>
        <p className="text-muted-foreground">
          Stock details and chart will be implemented in Phase 1A
        </p>

        <div className="grid gap-6 md:grid-cols-2">
          {/* Chart placeholder */}
          <div className="rounded-lg border bg-card p-6">
            <h2 className="text-lg font-semibold mb-4">Price Chart</h2>
            <div className="h-64 bg-muted rounded flex items-center justify-center">
              <span className="text-muted-foreground">
                TradingView chart coming soon
              </span>
            </div>
          </div>

          {/* Analysis placeholder */}
          <div className="rounded-lg border bg-card p-6">
            <h2 className="text-lg font-semibold mb-4">AI Analysis</h2>
            <div className="h-64 bg-muted rounded flex items-center justify-center">
              <span className="text-muted-foreground">
                Claude analysis coming soon
              </span>
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}
