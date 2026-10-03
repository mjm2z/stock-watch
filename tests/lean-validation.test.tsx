import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { webcrypto } from 'node:crypto'
beforeAll(() =>
  Object.defineProperty(globalThis.crypto, 'getRandomValues', {
    value: webcrypto.getRandomValues.bind(webcrypto),
    configurable: true,
  })
)
import { LeanValidation } from '@/components/LeanValidation'
jest.mock('@/components/OperatorSession', () => ({ useOperator: () => ({ authenticated: true }) }))
jest.mock('@/components/dashboard/SystemEquityChart', () => ({ SystemEquityChart: () => null }))
const versions = [{ id: 'v', asset: 'bitcoin', template: 'trend', config_json: '{}' }],
  datasets = [{ id: 'd', asset: 'bitcoin', manifest_json: '{"timeframe":"1Hour"}' }]
test('runner unavailable disables submission', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ health: { configured: false }, runs: [] }),
  })
  render(<LeanValidation versions={versions} datasets={datasets} />)
  expect(await screen.findByText('Runner not configured')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Preview comparison' })).toBeDisabled()
})
test('preview submits stable research identity after a failed acknowledgement', async () => {
  const ids: string[] = []
  global.fetch = jest.fn().mockImplementation(async (_url, options) => {
    if (options?.method === 'POST') {
      ids.push(JSON.parse(options.body).id)
      return { ok: false, json: async () => ({ error: 'Connection lost' }) }
    }
    return {
      ok: true,
      json: async () => ({ health: { configured: true, healthy: true }, runs: [] }),
    }
  })
  render(<LeanValidation versions={versions} datasets={datasets} />)
  await screen.findByText('Runner available')
  fireEvent.change(screen.getByLabelText('LEAN system version'), { target: { value: 'v' } })
  fireEvent.change(screen.getByLabelText('LEAN dataset'), { target: { value: 'd' } })
  fireEvent.click(screen.getByRole('button', { name: 'Preview comparison' }))
  fireEvent.click(screen.getByRole('button', { name: 'Run comparison' }))
  await screen.findByText('Connection lost')
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Run comparison' })).not.toBeDisabled()
  )
  fireEvent.click(screen.getByRole('button', { name: 'Run comparison' }))
  await waitFor(() => expect(ids).toHaveLength(2))
  expect(ids[0]).toBe(ids[1])
})
