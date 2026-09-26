import { systemDetail } from '@/lib/research-control'
import { SystemEvidence } from '@/components/SystemEvidence'
export const dynamic = 'force-dynamic'
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  try {
    return <SystemEvidence data={systemDetail((await params).id)} />
  } catch {
    return (
      <main className="sw-page">
        <h1>System unavailable</h1>
        <p>Check worker migration and the system identifier.</p>
      </main>
    )
  }
}
