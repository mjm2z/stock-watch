import { BitcoinWorkspace } from '@/components/BitcoinWorkspace'
export const dynamic = 'force-dynamic'
export default async function BitcoinPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>
}) {
  const params = await searchParams
  const view = ['signals', 'paper', 'blockchain', 'operations'].includes(params.view || '')
    ? params.view!
    : 'overview'
  return <BitcoinWorkspace view={view} />
}
