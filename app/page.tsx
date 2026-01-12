import { StockSearch } from '@/components/StockSearch'

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-4 sm:p-8">
      <div className="w-full max-w-2xl space-y-8">
        {/* Header */}
        <div className="text-center space-y-3">
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
            Stock Watch
          </h1>
          <p className="text-lg text-muted-foreground sm:text-xl">
            AI-Powered Stock Research
          </p>
        </div>

        {/* Search */}
        <div className="w-full">
          <StockSearch autoFocus />
        </div>

        {/* Features hint */}
        <div className="text-center text-sm text-muted-foreground">
          <p>Type a ticker (AAPL) or company name, press Enter to search</p>
        </div>

        {/* Quality filters info */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 text-center text-xs text-muted-foreground pt-8">
          <div className="space-y-1">
            <div className="font-medium">Market Cap</div>
            <div>$500M+</div>
          </div>
          <div className="space-y-1">
            <div className="font-medium">Stock Price</div>
            <div>$5+</div>
          </div>
          <div className="space-y-1">
            <div className="font-medium">Daily Volume</div>
            <div>500K+</div>
          </div>
          <div className="space-y-1">
            <div className="font-medium">Exchanges</div>
            <div>NYSE, NASDAQ, AMEX</div>
          </div>
        </div>
      </div>
    </main>
  )
}
