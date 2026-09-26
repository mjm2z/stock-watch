import { SystemsWorkspace } from '@/components/SystemsWorkspace'
export const dynamic = 'force-dynamic'
export default async function SystemsPage({
  searchParams,
}: {
  searchParams: Promise<{ asset?: string }>
}) {
  const params = await searchParams
  return (
    <SystemsWorkspace
      key={params.asset === 'bitcoin' ? 'bitcoin' : 'stocks'}
      asset={params.asset === 'bitcoin' ? 'bitcoin' : 'stocks'}
    />
  )
}
