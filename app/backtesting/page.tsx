import { ResearchWorkspace } from '@/components/ResearchWorkspace'
export const metadata = { title: 'Backtesting' }
export const dynamic = 'force-dynamic'
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ asset?: string }>
}) {
  const p = await searchParams
  return (
    <ResearchWorkspace
      key={p.asset || 'stocks'}
      mode="backtesting"
      asset={p.asset === 'bitcoin' || p.asset === 'crypto' ? 'bitcoin' : 'stocks'}
    />
  )
}
