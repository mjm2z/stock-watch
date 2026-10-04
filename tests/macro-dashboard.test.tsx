import { render, screen } from '@testing-library/react'
import { MacroDashboard } from '@/components/MacroDashboard'
const original = global.fetch
afterEach(() => {
  global.fetch = original
})
test('unconfigured service is explicit and does not invent observations', async () => {
  global.fetch = jest.fn(async () => ({
    ok: true,
    json: async () => ({ configured: false, healthy: false, status: 'unconfigured', series: [] }),
  })) as jest.Mock
  render(<MacroDashboard />)
  expect(await screen.findByText('FRED API key has not been configured.')).toBeInTheDocument()
  expect(screen.queryByText('Inflation')).not.toBeInTheDocument()
})
test('retained observations remain visible and dated on provider failure', async () => {
  global.fetch = jest.fn(async () => ({
    ok: true,
    json: async () => ({
      configured: true,
      healthy: false,
      status: 'provider_unavailable',
      stale: true,
      updated_at: 1700000000,
      series: [
        {
          id: 'UNRATE',
          label: 'Unemployment',
          publisher: 'BLS',
          source_url: 'https://fred.stlouisfed.org/series/UNRATE',
          metadata: { seasonal_adjustment: 'Seasonally Adjusted' },
          latest: { period: '2020-01-01', value: null, units: 'Percent' },
          history: [],
        },
      ],
    }),
  })) as jest.Mock
  render(<MacroDashboard />)
  expect(await screen.findByText(/Updates unavailable or stale/)).toBeInTheDocument()
  expect(screen.getByText('Observation period: 2020-01-01')).toBeInTheDocument()
  expect(screen.getByText('Unavailable')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /View source/ })).toHaveAttribute(
    'href',
    'https://fred.stlouisfed.org/series/UNRATE'
  )
})
