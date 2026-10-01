import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StockMarketChart } from '@/components/StockMarketChart'
import { clearChartHistoryCache } from '@/components/useChartHistory'
import { ChartControls } from '@/components/ChartControls'
jest.mock('@/components/StockSearch', () => ({
  StockSearch: ({ onSelect }: any) => (
    <div>
      {['AAPL', 'QQQ', 'DIA', 'MSFT', 'NVDA'].map((ticker) => (
        <button key={ticker} onClick={() => onSelect({ ticker })}>
          Add {ticker}
        </button>
      ))}
    </div>
  ),
}))
jest.mock('@/components/MarketChart', () => ({
  InteractiveChart: (p: any) => (
    <div data-testid="chart">
      {JSON.stringify({
        label: p.label,
        percent: p.percent,
        style: p.style,
        comparisons: p.comparisons?.map((s: any) => s.name),
        close: p.bars[0]?.close,
      })}
    </div>
  ),
}))
const response = {
  ok: true,
  json: async () => ({
    data: [
      { date: '2026-09-01T00:00:00Z', open: 100, high: 110, low: 90, close: 100, volume: 20 },
      { date: '2026-09-02T00:00:00Z', open: 110, high: 120, low: 100, close: 110, volume: 30 },
    ],
    meta: { adjustment: 'all' },
  }),
}
beforeEach(() => {
  clearChartHistoryCache()
  localStorage.clear()
  global.fetch = jest.fn().mockResolvedValue(response)
})
test('adds five total, switches to comparison lines, supports dollars, rejects duplicates and removes symbols', async () => {
  render(<StockMarketChart />)
  await screen.findByTestId('chart')
  fireEvent.click(screen.getByText('Add AAPL'))
  await waitFor(() =>
    expect(screen.getAllByTestId('chart')[0]).toHaveTextContent('"comparisons":["AAPL"]')
  )
  expect(screen.getByLabelText('Chart style')).toBeDisabled()
  expect(screen.getByRole('radio', { name: 'Percentage change' })).toHaveAttribute(
    'aria-checked',
    'true'
  )
  fireEvent.click(screen.getByRole('radio', { name: 'Dollar prices' }))
  expect(screen.getAllByTestId('chart')[0]).toHaveTextContent('"percent":false')
  fireEvent.click(screen.getByText('Add AAPL'))
  expect(screen.getByText('AAPL is already on the chart.')).toBeInTheDocument()
  for (const s of ['QQQ', 'DIA', 'MSFT', 'NVDA']) fireEvent.click(screen.getByText('Add ' + s))
  expect(screen.getByText(/five maximum/)).toBeInTheDocument()
  expect(screen.queryByLabelText('Remove NVDA')).not.toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Remove AAPL'))
  expect(screen.queryByLabelText('Remove AAPL')).not.toBeInTheDocument()
  await act(async () => {})
})
test('removed loading stock cannot be restored by its late response', async () => {
  let resolve!: (v: any) => void
  ;(global.fetch as jest.Mock).mockImplementation((url: string) =>
    url.includes('/AAPL/') ? new Promise((r) => (resolve = r)) : Promise.resolve(response)
  )
  render(<StockMarketChart />)
  await screen.findByTestId('chart')
  fireEvent.click(screen.getByText('Add AAPL'))
  await screen.findByLabelText('Loading AAPL')
  fireEvent.click(screen.getByLabelText('Remove AAPL'))
  await act(async () => resolve(response))
  expect(screen.queryByLabelText('Remove AAPL')).not.toBeInTheDocument()
})
test('custom range applies inclusive end only after confirmation', () => {
  HTMLDialogElement.prototype.showModal = jest.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
  })
  HTMLDialogElement.prototype.close = jest.fn(function (this: HTMLDialogElement) {
    this.removeAttribute('open')
  })
  const onCustom = jest.fn(),
    onRange = jest.fn()
  render(
    <ChartControls
      range="1M"
      onRange={onRange}
      ranges={['1M']}
      custom={{ start: '', end: '' }}
      onCustom={onCustom}
      style="line"
      onStyle={() => {}}
      volume={false}
      onVolume={() => {}}
    />
  )
  fireEvent.click(screen.getByText('Custom'))
  fireEvent.change(screen.getByLabelText('Start'), { target: { value: '2026-01-01' } })
  fireEvent.change(screen.getByLabelText('End'), { target: { value: '2026-01-02' } })
  expect(onCustom).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Apply'))
  expect(onCustom).toHaveBeenCalledWith({
    start: '2026-01-01T00:00:00.000Z',
    end: '2026-01-03T00:00:00.000Z',
  })
})
