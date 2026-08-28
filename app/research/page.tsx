import { StockSearch } from '@/components/StockSearch'

export default function ResearchPage() {
  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] flex-col items-center justify-center p-4 sm:p-8">
      <div className="w-full max-w-2xl space-y-8">
        <div className="space-y-3 text-center">
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">Explore a company</h1>
          <p className="text-lg text-muted-foreground">
            Search quotes, charts, fundamentals, and manual research notes.
          </p>
        </div>
        <StockSearch autoFocus />
        <p className="text-center text-sm text-muted-foreground">
          Type a ticker or company name, then press Enter.
        </p>
      </div>
    </main>
  )
}
