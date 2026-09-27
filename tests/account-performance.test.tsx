jest.mock('server-only', () => ({}))
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { render, screen, fireEvent } from '@testing-library/react'
import { accountPerformance } from '@/lib/performance-store'
import { AccountReturnCurve } from '@/components/AccountReturnCurve'
const original = process.env.STOCK_WATCH_DATABASE_PATH
let directory: string
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'account-performance-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'fixture.db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  db.exec(readFileSync('worker/migrations/020_correctness.sql', 'utf8'))
  db.close()
})
afterEach(() => {
  if (original === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = original
  rmSync(directory, { recursive: true, force: true })
})
test('chart window cannot change full-period metrics or combine account scopes', () => {
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH!)
  const result = {
    scope: 'stocks_account',
    owner: 'stocks',
    as_of: '2026-01-01T00:09:00Z',
    available: true,
    intervals: 599,
    return: 0.12,
    maximum_drawdown: -0.35,
  }
  db.prepare('INSERT INTO performance_results VALUES (?,?,?,?,?)').run(
    result.scope,
    result.owner,
    'test',
    result.as_of,
    JSON.stringify(result)
  )
  for (let i = 0; i < 600; i++)
    db.prepare('INSERT INTO performance_marks VALUES (?,?,?,?,?,?,?,?,?)').run(
      result.scope,
      result.owner,
      new Date(Date.parse('2026-01-01T00:00:00Z') + i * 1000).toISOString(),
      '100',
      '100',
      '0',
      1,
      1,
      JSON.stringify({ return_index: 100 })
    )
  db.close()
  const data = accountPerformance('stocks')
  expect(data.result?.maximum_drawdown).toBe(-0.35)
  expect('points' in data && data.points).toHaveLength(500)
  expect(accountPerformance('bitcoin').available).toBe(false)
})
test('return chart preserves gaps and supports keyboard point inspection', () => {
  const { container } = render(
    <AccountReturnCurve
      points={[
        { at: '2026-01-01', index: 100 },
        { at: '2026-01-02', index: null },
        { at: '2026-01-03', index: 105 },
      ]}
    />
  )
  const path = container.querySelector('path')!.getAttribute('d')!
  expect(path.match(/M/g)).toHaveLength(2)
  expect(path).not.toContain('L')
  fireEvent.change(screen.getByRole('slider'), { target: { value: 1 } })
  expect(screen.getByText(/Return index unavailable/)).toBeInTheDocument()
})
