import { PageHeader } from '@/components/PageHeader'
import { AssessmentControls } from '@/components/dashboard/AssessmentControls'
import { StockSearch } from '@/components/StockSearch'
import { Watchlist } from '@/components/Watchlist'
import { ResearchJournal } from '@/components/ResearchJournal'
export const dynamic = 'force-dynamic'
export default async function ResearchPage({
  searchParams,
}: {
  searchParams: Promise<{ symbol?: string }>
}) {
  const { symbol } = await searchParams
  return (
    <main className="container mx-auto space-y-6 p-4 sm:p-8">
      <PageHeader title="Research workspace" description="Shared watchlist, research history, and evidence to review against future outcomes." />
      <StockSearch />
      <Watchlist />
      <form className="flex flex-wrap gap-3">
        <input
          name="symbol"
          defaultValue={symbol}
          placeholder="Filter journal by ticker"
          aria-label="Journal ticker filter"
          className="min-w-0 max-w-full rounded-md border bg-background px-3 py-2"
        />
        <button className="rounded-md border px-4 py-2">Filter journal</button>
        <a className="p-2 text-primary" href="/research">
          Clear
        </a>
      </form>
      <ResearchJournal key={symbol ?? ''} symbol={symbol} />
      <section id="experiments">
        <AssessmentControls research />
      </section>
    </main>
  )
}

export const metadata = { title: 'Research' }
