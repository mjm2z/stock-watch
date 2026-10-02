import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CompanyInformation } from '@/components/CompanyInformation'
const body = (symbol: string, kind = 'company') => ({
  symbol,
  status: 'ready',
  data: {
    name: symbol + ' issuer',
    cik: '0000320193',
    kind,
    observedAt: '2026-10-02T00:00:00Z',
    metrics: [
      {
        label: 'Revenue',
        value: 100,
        unit: 'USD',
        periodLabel: 'Annual',
        end: '2025-12-31',
        filed: '2026-02-01',
        url: 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/0000320193-26-000001-index.html',
      },
    ],
    filings: [
      {
        accession: '0000320193-26-000001',
        form: '8-K',
        filed: '2026-09-30',
        earningsRelated: true,
        url: 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/0000320193-26-000001-index.html',
      },
    ],
  },
})
test('selects newly added ticker, ignores a late response from the old company and filters disclosures', async () => {
  let complete!: (value: unknown) => void
  global.fetch = jest.fn().mockImplementation((url: string) =>
    url.includes('/SPY/')
      ? new Promise((r) => {
          complete = r
        })
      : Promise.resolve({ ok: true, json: async () => body('AAPL') })
  )
  const { rerender } = render(<CompanyInformation symbols={['SPY']} />)
  rerender(<CompanyInformation symbols={['SPY', 'AAPL']} />)
  await screen.findByText(/AAPL issuer/)
  await act(async () => complete({ ok: true, json: async () => body('SPY', 'fund') }))
  expect(screen.queryByText(/SPY issuer/)).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Filing filter'), { target: { value: 'earnings' } })
  expect(screen.getByRole('link', { name: /8-K/ })).toHaveAttribute(
    'href',
    expect.stringContaining('https://www.sec.gov/Archives/')
  )
  rerender(<CompanyInformation symbols={[]} />)
  expect(screen.getByText(/Add a stock/)).toBeInTheDocument()
})
test('fund view omits corporate financials and preserves stale filings on failure', async () => {
  global.fetch = jest
    .fn()
    .mockResolvedValue({
      ok: true,
      json: async () => ({
        ...body('SPY', 'fund'),
        status: 'unavailable',
        stale: true,
        error: 'SEC collection unavailable',
      }),
    })
  render(<CompanyInformation symbols={['SPY']} />)
  await screen.findByText(/Fund issuer filings/)
  expect(screen.queryByText('Revenue')).not.toBeInTheDocument()
  expect(screen.getByText(/Previously collected/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /8-K/ })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Check again' }))
  await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2))
})
