import { render, screen, fireEvent } from '@testing-library/react'
import { easternDayBoundary, executionLabel, incidentText } from '@/lib/dashboard-presentation'
import { EquityCurve } from '@/components/dashboard/EquityCurve'
import { PaperLots } from '@/components/dashboard/PaperLots'
import { ExperimentComparison } from '@/components/dashboard/ExperimentComparison'
import type { DashboardSignal, DashboardPortfolioLot } from '@/types/dashboard'

test('Eastern day bounds include spring and fall DST changes', () => {
  expect(easternDayBoundary('2026-03-08')).toBe('2026-03-08T05:00:00.000Z')
  expect(easternDayBoundary('2026-03-08', true)).toBe('2026-03-09T04:00:00.000Z')
  expect(easternDayBoundary('2026-11-01')).toBe('2026-11-01T04:00:00.000Z')
  expect(easternDayBoundary('2026-11-01', true)).toBe('2026-11-02T05:00:00.000Z')
  expect(() => easternDayBoundary('2026-02-30')).toThrow('valid calendar date')
})
test('execution labels distinguish qualification from data blocks and actual order status', () => {
  const signal = {
    decision: 'qualified',
    orderStatus: null,
    qualityReview: { blockers: ['missing'] },
  } as DashboardSignal
  expect(executionLabel(signal)).toBe('Blocked by data checks')
  expect(executionLabel({ ...signal, orderStatus: 'filled' })).toBe('Order: filled')
  expect(executionLabel({ ...signal, qualityReview: undefined })).toBe('No order recorded')
  expect(incidentText('immutable news article changed: alpaca:1')).toContain(
    'previously collected news article changed'
  )
})
test('equity chart breaks missing benchmark segments and exposes exact contribution values', () => {
  const history = [0, 1, 2].map((i) => ({
    observedAt: `2026-09-0${i + 1}T20:00:00Z`,
    equity: 10 + i,
    spyValue: i === 1 ? null : 10 + i,
    contributedCapital: 10,
    realizedPnl: 0,
    unrealizedPnl: i,
  }))
  const { container } = render(<EquityCurve history={history} />)
  const spyPath = container.querySelectorAll('path')[1].getAttribute('d')!
  expect(spyPath.match(/M/g)).toHaveLength(2)
  expect(spyPath).not.toContain('L')
  fireEvent.change(screen.getByRole('slider', { name: 'Snapshot' }), { target: { value: '1' } })
  expect(screen.getByText(/SPY Unavailable · Contributions \$10.00/)).toBeInTheDocument()
})
test('unfilled orders and pending exits are not presented as zero returns', () => {
  render(
    <PaperLots
      lots={[
        {
          id: '1',
          symbol: 'MRK',
          horizonTradingDays: 5,
          status: 'pending',
          score: 76,
          entryNotionalUsd: 10,
          entryPrice: null,
          entryQuantity: null,
          openedAt: null,
          targetExitAt: '2026-11-27T17:55:00Z',
          closedAt: null,
          exitPrice: null,
          exitQuantity: null,
          realizedReturn: null,
          orderStatus: 'accepted',
          exitOrderStatus: null,
        } as DashboardPortfolioLot,
      ]}
    />
  )
  expect(screen.getByText('accepted')).toBeInTheDocument()
  expect(screen.getAllByText('Awaiting exit').length).toBeGreaterThan(0)
  expect(screen.getByText(/12:55/)).toBeInTheDocument()
  expect(screen.queryByText('0.00%')).not.toBeInTheDocument()
})
test('experiment selectors separate horizons and strategies', () => {
  render(
    <ExperimentComparison
      rows={[
        { strategy: 'v2', horizon: 5, variant: 'baseline-v1', matured: 0 },
        { strategy: 'v2', horizon: 21, variant: 'without-news-v1', matured: 30 },
      ]}
    />
  )
  expect(screen.getByText('Baseline weights and data checks')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Holding period'), { target: { value: '21' } })
  expect(screen.getByText('Without news')).toBeInTheDocument()
  expect(screen.queryByText('Baseline weights and data checks')).not.toBeInTheDocument()
})
