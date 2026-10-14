jest.mock('next/server', () => ({ NextResponse: { json: (body: unknown) => body } }))
jest.mock('@/lib/research-store', () => ({ researchDatabase: jest.fn() }))
import { GET } from '@/app/api/health/experiments/route'
import { researchDatabase } from '@/lib/research-store'

function rows(component: string, minutes: number, error: string | null = null) {
  return { component, at: new Date(Date.now() - minutes * 60_000).toISOString(), error }
}

function database(
  components: ReturnType<typeof rows>[],
  active: string[] = [],
  omit: string[] = []
) {
  const defaults = [
    'collection:stocks',
    'collection:bitcoin',
    'stream:stocks',
    'stream:bitcoin',
    'stock-baseline-owner',
    'stock-experiment-owner',
    'preflight:stocks',
    'news',
    'storage',
    'settlement-calendar',
  ]
  const combined = [
    ...defaults
      .filter((name) => !omit.includes(name) && !components.some((r) => r.component === name))
      .map((name) => rows(name, 1)),
    ...components,
  ]
  ;(researchDatabase as jest.Mock).mockImplementation((_write, callback) =>
    callback({
      prepare: (sql: string) => ({
        all: () =>
          sql.includes('experiment_batches') ? active.map((asset) => ({ asset })) : combined,
      }),
    })
  )
}

test('hourly context remains healthy between polls while execution has a short heartbeat', async () => {
  database([rows('context:Federal Reserve', 60), rows('execution:stocks', 1)], ['stocks'])
  expect(await GET()).toMatchObject({ status: 'healthy' })
  database([rows('context:Federal Reserve', 60), rows('execution:stocks', 4)], ['stocks'])
  expect(await GET()).toMatchObject({ status: 'attention' })
  database([rows('context:Federal Reserve', 80)])
  expect(await GET()).toMatchObject({ status: 'attention' })
})

test('completed batches and fee-release events do not pretend to be active heartbeat failures', async () => {
  database([
    rows('collection:stocks', 1),
    rows('execution:stocks', 120, 'old incident'),
    rows('fee-reserve-release:bitcoin', 120),
  ])
  expect(await GET()).toMatchObject({ status: 'healthy' })
})

test('missing execution owners are visible even when collectors are healthy', async () => {
  database([], [], ['stock-experiment-owner'])
  expect(await GET()).toMatchObject({ status: 'attention', missing: ['stock-experiment-owner'] })
})
