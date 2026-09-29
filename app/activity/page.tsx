import { ActivityWorkspace } from '@/components/ActivityWorkspace'
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ asset?: string; scope?: string; symbol?: string }>
}) {
  const params = await searchParams
  return (
    <ActivityWorkspace
      asset={params.asset === 'bitcoin' ? 'bitcoin' : 'stocks'}
      initialScope={params.scope}
      initialSymbol={params.symbol}
    />
  )
}
export const metadata = { title: 'Activity' }
