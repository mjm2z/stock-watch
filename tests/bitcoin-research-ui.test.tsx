import { fireEvent, render, screen } from '@testing-library/react'
import { BitcoinSystemResearch } from '@/components/BitcoinSystemResearch'

test('research compares actual periods and distinguishes tests from trades', () => {
  render(<BitcoinSystemResearch compact />)
  expect(screen.getByRole('link', { name: 'Create a system' })).toHaveAttribute(
    'href',
    '/systems?asset=bitcoin&create=1'
  )
  expect(screen.getAllByText('Limited evidence')).toHaveLength(3)
  expect(screen.getByText(/10 runs per system = 5 periods/)).toBeInTheDocument()
  expect(screen.getAllByText('2026 YTD net return')).toHaveLength(3)
  fireEvent.change(screen.getByLabelText('Evaluation period'), { target: { value: '2022' } })
  expect(screen.getAllByText('2022 net return')).toHaveLength(3)
  expect(screen.getAllByRole('link', { name: 'Use as an editable draft' })).toHaveLength(3)
  expect(screen.getByRole('link', { name: /Download all runs/ })).toHaveAttribute(
    'href',
    '/api/systems/research/bitcoin'
  )
})
