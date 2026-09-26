import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { StockSearch } from '@/components/StockSearch'
import { ResearchJournal } from '@/components/ResearchJournal'
import { Navigation } from '@/components/Navigation'
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => '/signals',
  useSearchParams: () => new URLSearchParams(),
}))
jest.mock('@/lib/use-shared-watchlist', () => ({ useSharedWatchlist: () => ({ add: jest.fn() }) }))
const originalFetch = global.fetch
beforeEach(() => {
  global.fetch = jest.fn()
  if (!AbortSignal.any)
    Object.defineProperty(AbortSignal, 'any', {
      configurable: true,
      value: (signals: AbortSignal[]) => signals[0],
    })
  if (!AbortSignal.timeout)
    Object.defineProperty(AbortSignal, 'timeout', {
      configurable: true,
      value: () => new AbortController().signal,
    })
})
afterEach(() => {
  global.fetch = originalFetch
})
const response = (data: unknown, ok = true) => ({ ok, json: async () => data })
test('navigation has names and the active page remains identifiable on mobile', () => {
  render(<Navigation />)
  expect(screen.getByRole('link', { name: 'Signals' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('link', { name: 'Operations' })).toBeInTheDocument()
})
test('late search responses cannot replace the latest results', async () => {
  let finishOld!: (data: unknown) => void
  ;(fetch as jest.Mock)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishOld = resolve
        })
    )
    .mockResolvedValueOnce(
      response({ data: [{ ticker: 'MSFT', name: 'Microsoft', price: null, changePercent: null }] })
    )
  render(<StockSearch />)
  const input = screen.getByRole('combobox')
  fireEvent.change(input, { target: { value: 'AAPL' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search' }))
  fireEvent.change(input, { target: { value: 'MSFT' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search' }))
  expect(await screen.findByRole('option')).toHaveTextContent('MSFT')
  await act(async () =>
    finishOld(
      response({ data: [{ ticker: 'AAPL', name: 'Apple', price: null, changePercent: null }] })
    )
  )
  expect(screen.getByRole('option')).toHaveTextContent('MSFT')
  fireEvent.keyDown(input, { key: 'ArrowDown' })
  expect(input).toHaveAttribute('aria-activedescendant', screen.getByRole('option').id)
})
test('failed research saves preserve the entered thesis and show a recoverable error', async () => {
  ;(fetch as jest.Mock)
    .mockResolvedValueOnce(response({ notes: [] }))
    .mockResolvedValueOnce(response({ error: 'Save unavailable' }, false))
  const { container } = render(<ResearchJournal />)
  await screen.findByText('No journal entries in this view yet.')
  fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: 'AAPL' } })
  fireEvent.change(screen.getByLabelText('Hypothesis'), { target: { value: 'Thesis to preserve' } })
  fireEvent.submit(container.querySelector('form')!)
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Save unavailable'))
  expect(screen.getByLabelText('Hypothesis')).toHaveValue('Thesis to preserve')
  expect(screen.getByLabelText('Ticker')).toHaveValue('AAPL')
})
