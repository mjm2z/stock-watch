import { SystemsWorkspace } from '@/components/SystemsWorkspace'
import { BitcoinAutomationWorkspace } from '@/components/BitcoinAutomationWorkspace'
export const dynamic = 'force-dynamic'
export default async function SystemsPage({
  searchParams,
}: {
  searchParams: Promise<{ asset?: string; legacy?: string }>
}) {
  const params = await searchParams
  if (params.asset === 'bitcoin' && params.legacy !== '1') return <BitcoinAutomationWorkspace />
  return (
    <SystemsWorkspace
      key={params.asset === 'bitcoin' ? 'bitcoin' : 'stocks'}
      asset={params.asset === 'bitcoin' ? 'bitcoin' : 'stocks'}
    />
  )
}
