import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { LeanResearchValidation } from '@/components/LeanValidation'
import { ResearchWorkspace } from '@/components/ResearchWorkspace'
jest.mock('@/components/OperatorSession', () => ({
  useOperator: () => ({ authenticated: false, configured: true }),
}))
jest.mock('@/components/dashboard/SystemEquityChart', () => ({
  SystemEquityChart: () => <div>Equity chart</div>,
}))
jest.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }))
jest.mock('@/components/BitcoinSystemResearch', () => ({ BitcoinSystemResearch: () => null }))
jest.mock('@/components/ResearchActivity', () => ({ ResearchActivity: () => null }))
jest.mock('@/components/ResearchControl', () => ({ ResearchControl: () => null }))
jest.mock('@/components/ResearchLab', () => ({ ResearchLab: () => null }))
const original = global.fetch
beforeEach(() => {
  global.fetch = jest.fn(async (url) => ({
    ok: true,
    json: async () =>
      String(url).includes('/workspace')
        ? {
            versions: [],
            datasets: [],
            drafts: [],
            jobs: [],
            runs: [],
            deployments: [],
            qualifications: [],
            allocations: [],
            enrollments: [],
          }
        : String(url).includes('/api/systems?')
          ? {
              versions: [
                { id: 'trend-id', asset: 'bitcoin', template: 'trend', config_json: '{}' },
              ],
              datasets: [
                { id: 'hourly-id', asset: 'bitcoin', manifest_json: '{"timeframe":"1Hour"}' },
              ],
            }
          : String(url).includes('/api/lean/')
            ? {
                summary: {
                  outcome: 'matched',
                  difference_count: 0,
                  baseline: { ending_equity: 300, fees: 0, maximum_drawdown: 0 },
                  lean: { ending_equity: 300, fees: 0, maximum_drawdown: 0 },
                  limitations: [],
                  differences: [],
                  tolerances: {},
                },
              }
            : {
                health: { healthy: true, configured: true },
                runs: [
                  {
                    id: 'f88ac8db-ae06-549e-af58-5ba17958366f',
                    status: 'complete',
                    created_at: '2026-10-03T15:51:33Z',
                  },
                ],
              },
  })) as jest.Mock
})
afterEach(() => {
  global.fetch = original
})
test('normal Bitcoin Systems library exposes LEAN without legacy route', async () => {
  render(<ResearchWorkspace asset="bitcoin" />)
  expect(await screen.findByRole('region', { name: 'LEAN validation' })).toBeInTheDocument()
  expect(await screen.findByText('trend · trend-id')).toBeInTheDocument()
})
test('read-only users can inspect results but cannot queue research', async () => {
  render(<LeanResearchValidation />)
  await screen.findByText('trend · trend-id')
  fireEvent.change(screen.getByLabelText('LEAN system version'), { target: { value: 'trend-id' } })
  fireEvent.change(screen.getByLabelText('LEAN dataset'), { target: { value: 'hourly-id' } })
  expect(screen.getByRole('button', { name: 'Preview comparison' })).toBeDisabled()
  fireEvent.click(await screen.findByRole('button', { name: 'Comparison f88ac8db' }))
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/lean/f88ac8db-ae06-549e-af58-5ba17958366f',
      expect.anything()
    )
  )
})
