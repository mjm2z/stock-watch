import { ManualPaperWorkspace } from '@/components/ManualPaperWorkspace'
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ asset?: string }>
}) {
  const params = await searchParams
  return <ManualPaperWorkspace initialAsset={params.asset === 'bitcoin' ? 'bitcoin' : 'stocks'} />
}
export const metadata = { title: 'Manual paper trading' }
