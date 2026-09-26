import { render, screen, waitFor } from '@testing-library/react'
import { BitcoinAutomationWorkspace } from '@/components/BitcoinAutomationWorkspace'
const originalFetch = global.fetch
beforeEach(() => {
  global.fetch = jest.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith('/session')
        ? { authenticated: false, configured: false }
        : {
            versions: [],
            evaluations: [],
            orders: [],
            commands: [],
            health: [],
            forward: [],
            fees: [],
            account: null,
          },
  })) as jest.Mock
})
afterEach(() => {
  global.fetch = originalFetch
})
test('read-only automation explains evidence and preserves stock and legacy navigation', async () => {
  render(<BitcoinAutomationWorkspace />)
  await waitFor(() =>
    expect(screen.getByText(/Operator access is not configured/i)).toBeInTheDocument()
  )
  expect(screen.getByRole('button', { name: 'Create version' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Apply funding plan' })).toBeDisabled()
  expect(screen.getByLabelText('Decision timeframe').querySelectorAll('option')).toHaveLength(8)
  expect(screen.getByRole('link', { name: 'Stock systems' })).toHaveAttribute(
    'href',
    '/systems?asset=stocks'
  )
  expect(screen.getByRole('link', { name: 'Earlier research and deployments' })).toHaveAttribute(
    'href',
    '/systems?asset=bitcoin&legacy=1'
  )
  expect(screen.getByText(/100 scenarios \+ 30 forward days/)).toBeInTheDocument()
})
