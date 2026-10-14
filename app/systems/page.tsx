import { ExperimentsWorkspace } from '@/components/ExperimentsWorkspace'
import { ResearchWorkspace } from '@/components/ResearchWorkspace'
import { SystemsWorkspace } from '@/components/SystemsWorkspace'
import { BitcoinAutomationWorkspace } from '@/components/BitcoinAutomationWorkspace'
export const dynamic = 'force-dynamic'
export default async function SystemsPage({
  searchParams,
}: {
  searchParams: Promise<{ asset?: string; legacy?: string; advanced?: string; tab?: string }>
}) {
  const params = await searchParams
  if (params.tab === 'experiments')
    return (
      <ExperimentsWorkspace
        key={params.asset || 'stocks'}
        asset={params.asset === 'bitcoin' ? 'bitcoin' : 'stocks'}
      />
    )
  if (params.asset === 'bitcoin' && params.advanced === '1') return <BitcoinAutomationWorkspace />
  if (params.legacy !== '1')
    return (
      <ResearchWorkspace
        key={params.asset || 'stocks'}
        asset={params.asset === 'bitcoin' || params.asset === 'crypto' ? 'bitcoin' : 'stocks'}
      />
    )
  return (
    <SystemsWorkspace
      key={params.asset === 'bitcoin' ? 'bitcoin' : 'stocks'}
      asset={params.asset === 'bitcoin' ? 'bitcoin' : 'stocks'}
    />
  )
}

export const metadata = { title: 'Systems' }
