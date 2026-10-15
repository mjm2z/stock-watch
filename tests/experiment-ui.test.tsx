import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ExperimentsWorkspace } from '@/components/ExperimentsWorkspace'
import { useOperator } from '@/components/OperatorSession'
import { families, type ExperimentData } from '@/components/experiments/presentation'

jest.mock('@/components/OperatorSession', () => ({ useOperator: jest.fn() }))
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, ...props }: { children: React.ReactNode }) => <a {...props}>{children}</a>,
}))

function fixture(): ExperimentData {
  return {
    batches: [
      {
        id: 'batch-123',
        revision: 'revision-123',
        status: 'preview',
        created: new Date().toISOString(),
        equity: '1000',
        expires: new Date(Date.now() + 30 * 86400000).toISOString(),
        risk_reason: null,
        plan: {
          versions: families.map((family) => ({
            family,
            universe: ['SPY'],
            holding_minutes: family === 'control' ? 15 : 120,
            stop: '0.01',
            take: '0.02',
          })),
        },
      },
    ],
    instances: [],
    health: [],
    commands: [],
    research: [],
    proposals: [],
    context: Array.from({ length: 8 }, (_, i) => ({
      id: String(i),
      source: i % 2 ? 'SEC EDGAR' : 'Federal Reserve',
      symbol: i % 2 ? 'SPY' : null,
      title: 'Research update ' + i,
      url: 'https://example.com/' + i,
      published: new Date().toISOString(),
      observed: new Date().toISOString(),
    })),
  }
}
const previous = global.fetch
let data: ExperimentData
let fetchMock: jest.Mock
beforeEach(() => {
  data = fixture()
  ;(useOperator as jest.Mock).mockReturnValue({ authenticated: false, configured: true })
  fetchMock = jest
    .fn()
    .mockImplementation(async (_url, options) => ({
      ok: true,
      json: async () =>
        options?.method === 'POST' ? { id: 'queued-request', status: 'queued' } : data,
    }))
  global.fetch = fetchMock
})
afterEach(() => {
  global.fetch = previous
  jest.restoreAllMocks()
})

test.each(['stocks', 'bitcoin'] as const)(
  'preparing a %s batch works without randomUUID on HTTP',
  async (asset) => {
    jest.replaceProperty(globalThis, 'crypto', { getRandomValues: crypto.getRandomValues } as Crypto)
    ;(useOperator as jest.Mock).mockReturnValue({ authenticated: true, configured: true })
    data.batches = []
    const user = userEvent.setup()
    render(<ExperimentsWorkspace asset={asset} />)
    await user.click(await screen.findByRole('button', { name: 'Prepare batch preview' }))
    const requests = fetchMock.mock.calls.filter((call) => call[1]?.method === 'POST')
    expect(requests).toHaveLength(1)
    expect(JSON.parse(requests[0][1].body)).toEqual({
      action: 'preview',
      asset,
      requestId: expect.stringMatching(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
      ),
    })
    expect(screen.getByRole('button', { name: 'Preparing preview…' })).toBeDisabled()
  }
)

test('a frozen preview is presented as cards and remains read-only until operator approval', async () => {
  render(<ExperimentsWorkspace asset="stocks" />)
  await screen.findByText('Review your experiments')
  expect(screen.getByRole('button', { name: 'Approve batch' })).toBeDisabled()
  expect(
    within(screen.getByRole('region', { name: 'Experiments' })).getAllByRole('article')
  ).toHaveLength(5)
  expect(screen.getByRole('article', { name: 'Trend following' })).toHaveTextContent('$200.00')
  expect(screen.getByText(/Four \$200 strategies/)).toBeInTheDocument()
  expect(screen.queryByText('Research update 0')).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.every((call) => !call[1]?.method)).toBe(true)
})

test('research expands by keyboard, is paged in small groups and can be filtered without trading', async () => {
  const user = userEvent.setup()
  render(<ExperimentsWorkspace asset="stocks" />)
  const trigger = await screen.findByRole('button', { name: /Research brief/ })
  trigger.focus()
  await user.keyboard('{Enter}')
  expect(trigger).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getAllByRole('link', { name: /Research update/ })).toHaveLength(3)
  const pager = screen.getByRole('navigation', { name: 'Research brief pages' })
  await user.click(within(pager).getByRole('button', { name: 'Next' }))
  expect(screen.getByRole('link', { name: 'Research update 3' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'SEC' }))
  expect(screen.getByRole('link', { name: 'Research update 1' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Research update 0' })).not.toBeInTheDocument()
  await user.click(trigger)
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('link', { name: /Research update/ })).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.every((call) => !call[1]?.method)).toBe(true)
})

test('approval explicitly sends the frozen batch revision and prevents duplicate requests', async () => {
  jest.replaceProperty(globalThis, 'crypto', { getRandomValues: crypto.getRandomValues } as Crypto)
  ;(useOperator as jest.Mock).mockReturnValue({ authenticated: true, configured: true })
  const user = userEvent.setup()
  render(<ExperimentsWorkspace asset="bitcoin" />)
  await user.click(await screen.findByRole('button', { name: 'Approve batch' }))
  await waitFor(() =>
    expect(fetchMock.mock.calls.filter((call) => call[1]?.method === 'POST')).toHaveLength(1)
  )
  const request = fetchMock.mock.calls.find((call) => call[1]?.method === 'POST')
  expect(JSON.parse(request![1].body)).toMatchObject({
    action: 'approve',
    asset: 'bitcoin',
    batch_id: 'batch-123',
    revision: 'revision-123',
  })
  expect(screen.getByRole('button', { name: 'Approving…' })).toBeDisabled()
})

test('an expired preview offers refresh and never sends an approval', async () => {
  ;(useOperator as jest.Mock).mockReturnValue({ authenticated: true, configured: true })
  data.batches[0].created = new Date(Date.now() - 31 * 60000).toISOString()
  const user = userEvent.setup()
  render(<ExperimentsWorkspace asset="stocks" />)
  await user.click(await screen.findByRole('button', { name: 'Refresh preview' }))
  const request = fetchMock.mock.calls.find((call) => call[1]?.method === 'POST')
  expect(JSON.parse(request![1].body).action).toBe('preview')
})

test('pending preflight does not disable the active batch pause control', async () => {
  ;(useOperator as jest.Mock).mockReturnValue({ authenticated: true, configured: true })
  data.batches[0].status = 'active'
  data.commands = [{ id: 'slow-preview', action: 'preview', status: 'pending', result_json: null }]
  data.instances = [
    {
      id: 'instance-123',
      batch_id: 'batch-123',
      family: 'trend',
      budget: '200',
      cash: '200',
      state: 'waiting_signal',
      reason: 'waiting_signal',
      last_decision: null,
      paused: 0,
    },
  ]
  render(<ExperimentsWorkspace asset="stocks" />)
  expect(await screen.findByRole('button', { name: 'Pause batch' })).toBeEnabled()
  expect(
    within(screen.getByRole('article', { name: 'Trend following' })).getByRole('button', {
      name: 'Pause',
    })
  ).toBeEnabled()
})
