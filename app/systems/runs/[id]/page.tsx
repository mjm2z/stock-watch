import { runDetail } from '@/lib/research-control'
import { RunEvidence } from '@/components/SystemEvidence'
export const dynamic = 'force-dynamic'
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  try {
    return <RunEvidence data={runDetail((await params).id)} />
  } catch {
    return (
      <main className="sw-page">
        <h1>Run unavailable</h1>
        <p>The run may still be preparing data. Return to activity to see its status.</p>
      </main>
    )
  }
}
