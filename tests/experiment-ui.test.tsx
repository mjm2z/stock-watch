import { render, screen, waitFor } from '@testing-library/react'
import { ExperimentsWorkspace } from '@/components/ExperimentsWorkspace'
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, ...props }: { children: React.ReactNode }) => <a {...props}>{children}</a>,
}))
test('a frozen preview remains read-only until an operator explicitly approves it', async () => {
  const fetchMock = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      batches: [
        {
          id: 'batch-123',
          revision: 'revision-123',
          status: 'preview',
          equity: '1000',
          expires: '2026-11-14T00:00:00Z',
          risk_reason: null,
          plan: {
            versions: [
              {
                family: 'trend',
                universe: ['SPY'],
                holding_minutes: 120,
                stop: '0.01',
                take: '0.02',
              },
            ],
          },
        },
      ],
      instances: [],
      health: [],
      commands: [],
      research: [],
      proposals: [],
      context: [],
    }),
  })
  const previous = global.fetch
  global.fetch = fetchMock
  try {
    render(<ExperimentsWorkspace asset="stocks" />)
    await waitFor(() => expect(screen.getByText('Review this batch')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Approve this paper batch' })).toBeDisabled()
    expect(screen.getByText(/Four \$200 strategies/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.every((call) => !call[1]?.method)).toBe(true)
  } finally {
    global.fetch = previous
  }
})
