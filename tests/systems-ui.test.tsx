import { render, screen, waitFor } from '@testing-library/react'
import { SystemsWorkspace } from '@/components/SystemsWorkspace'
import { BitcoinWorkspace } from '@/components/BitcoinWorkspace'
const originalFetch = global.fetch
beforeEach(() => {
  global.fetch = jest.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.endsWith('/session')
        ? { authenticated: false, configured: false }
        : url.startsWith('/api/systems')
          ? {
              versions: [],
              datasets: [],
              runs: [],
              deployments: [],
              observations: [],
              commands: [],
            }
          : { network: null, market: null, addresses: [], requests: [], transactions: [] },
  })) as jest.Mock
})
afterEach(() => {
  global.fetch = originalFetch
})
test('unconfigured systems remain readable and cannot start trading', async () => {
  render(<SystemsWorkspace asset="bitcoin" />)
  await waitFor(() =>
    expect(screen.getByText(/operator access is not configured/)).toBeInTheDocument()
  )
  expect(screen.getByRole('button', { name: 'Save immutable version' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Queue backtest' })).toBeDisabled()
  expect(screen.getByText(/No datasets imported/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Historical stock backtests' })).toHaveAttribute(
    'href',
    '/backtests'
  )
})
test('blockchain view explains address privacy and never substitutes zero for unknown balances', async () => {
  render(<BitcoinWorkspace view="blockchain" />)
  expect(await screen.findByText(/Address queries are sent to mempool.space/)).toBeInTheDocument()
  expect(screen.getByText('Awaiting fresh network observations')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Watch via public API' })).toBeDisabled()
})
