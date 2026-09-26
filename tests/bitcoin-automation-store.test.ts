jest.mock('server-only', () => ({}))
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { readBitcoinAutomation, writeBitcoinAutomation } from '@/lib/bitcoin-automation-store'
import { readSystems, writeSystems } from '@/lib/systems-store'
let directory: string
const original = process.env.STOCK_WATCH_DATABASE_PATH
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'bitcoin-automation-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'test.db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  for (const migration of ['016_systems', '017_bitcoin_automation'])
    db.exec(readFileSync(`worker/migrations/${migration}.sql`, 'utf8'))
  db.close()
})
afterEach(() => {
  if (original === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = original
  rmSync(directory, { recursive: true, force: true })
})
const create = (timeframe = '1Hour') =>
  writeBitcoinAutomation({
    action: 'create',
    timeframe,
    hypothesis: 'Trend persistence after costs',
  }).id

test('v2 hashes match Python and legacy records remain separate', () => {
  const id = create()
  expect(id).toBe('089c67b75bae2e96e0dc46f34e2f2b72d2ec446684e8b0fbbdb720721c26b6aa')
  expect(create()).toBe(id)
  expect(readBitcoinAutomation().versions).toHaveLength(1)
  expect(readSystems('bitcoin').versions).toHaveLength(0)
  expect(() => writeSystems({ action: 'shadow', version: id })).toThrow('collection')
  writeSystems({
    action: 'create',
    asset: 'stocks',
    template: 'trend',
    hypothesis: 'Legacy unchanged',
  })
  expect(readSystems('stocks').versions).toHaveLength(1)
})
test('all decision timeframes accept independent calendar holding durations', () => {
  for (const timeframe of ['1Min', '5Min', '15Min', '1Hour', '4Hour', '1Day', '1Week', '1Month']) {
    writeBitcoinAutomation({
      action: 'create',
      timeframe,
      holding_count: 12,
      holding_unit: 'months',
      hypothesis: 'Calendar duration',
    })
  }
  expect(readBitcoinAutomation().versions).toHaveLength(8)
  expect(() =>
    writeBitcoinAutomation({
      action: 'create',
      holding_count: 13,
      holding_unit: 'months',
      hypothesis: 'Invalid',
    })
  ).toThrow('holding')
  expect(() =>
    writeBitcoinAutomation({ action: 'create', allocation: 0.75, hypothesis: 'Invalid' })
  ).toThrow('Position size')
})
test('enrollment does not approve or fund; funding requires confirmation and is queued', () => {
  const version = create()
  writeBitcoinAutomation({ action: 'enroll', version })
  expect(readBitcoinAutomation().versions[0].approved_at).toBeNull()
  expect(() => writeBitcoinAutomation({ action: 'approve', version, confirmation: 'yes' })).toThrow(
    'version ID'
  )
  expect(() =>
    writeBitcoinAutomation({
      action: 'fund',
      versions: [version],
      confirmation: 'FUND BITCOIN PAPER',
    })
  ).toThrow('approved')
  writeBitcoinAutomation({ action: 'approve', version, confirmation: version })
  writeBitcoinAutomation({
    action: 'fund',
    versions: [version],
    confirmation: 'FUND BITCOIN PAPER',
  })
  expect(readBitcoinAutomation().commands[0].status).toBe('queued')
  expect(readBitcoinAutomation().account).toBeNull()
})
test('five active research versions are bounded and retired versions free a slot', () => {
  const versions = ['1Min', '5Min', '15Min', '1Hour', '4Hour', '1Day'].map(create)
  for (const version of versions.slice(0, 5)) writeBitcoinAutomation({ action: 'enroll', version })
  expect(() => writeBitcoinAutomation({ action: 'enroll', version: versions[5] })).toThrow('five')
  writeBitcoinAutomation({ action: 'retire', version: versions[0] })
  writeBitcoinAutomation({ action: 'enroll', version: versions[5] })
  expect(readBitcoinAutomation().versions.filter((v) => v.active === 1)).toHaveLength(5)
})
