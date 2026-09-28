import { act, render, screen } from '@testing-library/react'
import { BitcoinLivePrice } from '@/components/BitcoinLivePrice'
let source: {
  onmessage?: (event: { data: string }) => void
  onerror?: () => void
  close: jest.Mock
}
beforeEach(() => {
  global.EventSource = jest.fn().mockImplementation(() => {
    source = { close: jest.fn() }
    return source
  }) as unknown as typeof EventSource
})
test('initial snapshot, changed prices, reconnect retaining price and cleanup', () => {
  const view = render(<BitcoinLivePrice />)
  expect(screen.getByText('Live Price')).toBeInTheDocument()
  const tick = (price: number) =>
    act(() =>
      source.onmessage?.({
        data: JSON.stringify({
          price,
          fresh: true,
          status: 'Live',
          sourceAt: new Date().toISOString(),
          heartbeatAt: Date.now(),
        }),
      })
    )
  tick(100)
  expect(screen.getByText('$100.00')).toBeInTheDocument()
  tick(101)
  expect(screen.getByText('$101.00')).toBeInTheDocument()
  tick(99)
  expect(screen.getByText('$99.00')).toBeInTheDocument()
  act(() => source.onerror?.())
  expect(screen.getByText('Reconnecting')).toBeInTheDocument()
  expect(screen.getByText('$99.00')).toBeInTheDocument()
  expect(screen.getByText('$99.00').closest('p')).toHaveAttribute('aria-live', 'off')
  view.unmount()
  expect(source.close).toHaveBeenCalled()
})
