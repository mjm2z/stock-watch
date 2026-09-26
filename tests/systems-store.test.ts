jest.mock('server-only', () => ({}))
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { readSystems, writeSystems, readBitcoin } from '@/lib/systems-store'
import { login, authenticated } from '@/lib/systems-auth'
import type { NextRequest } from 'next/server'
let directory: string
const originalPath = process.env.STOCK_WATCH_DATABASE_PATH
const originalToken = process.env.SYSTEMS_OPERATOR_TOKEN
beforeEach(() => {
  directory = mkdtempSync(join(tmpdir(), 'stock-watch-systems-'))
  process.env.STOCK_WATCH_DATABASE_PATH = join(directory, 'systems.db')
  const db = new DatabaseSync(process.env.STOCK_WATCH_DATABASE_PATH)
  db.exec(readFileSync('worker/migrations/016_systems.sql', 'utf8'))
  db.close()
})
afterEach(() => {
  if (originalPath === undefined) delete process.env.STOCK_WATCH_DATABASE_PATH
  else process.env.STOCK_WATCH_DATABASE_PATH = originalPath
  if (originalToken === undefined) delete process.env.SYSTEMS_OPERATOR_TOKEN
  else process.env.SYSTEMS_OPERATOR_TOKEN = originalToken
  rmSync(directory, { recursive: true, force: true })
})
const create = (asset = 'bitcoin') =>
  writeSystems({ action: 'create', asset, template: 'trend', hypothesis: 'Persistence hypothesis' })
test('asset isolation and immutable template versions', () => {
  const first = create()
  expect(first.id).toBe('e664521e08effecaea9a67e44b54ccf858675184860ad186493eb0e8f4a5856d')
  expect(create().id).toBe(first.id)
  create('stocks')
  expect(readSystems('bitcoin').versions).toHaveLength(1)
  expect(readSystems('stocks').versions).toHaveLength(1)
  expect(() =>
    writeSystems({
      action: 'create',
      asset: 'bitcoin',
      template: 'trend',
      fast: 200,
      slow: 20,
      hypothesis: 'invalid',
    })
  ).toThrow('Lookbacks')
})
test('shadow creation is idempotently guarded and paper requires confirmation', () => {
  const version = create().id
  const deployment = writeSystems({ action: 'shadow', version }).id
  expect(() => writeSystems({ action: 'shadow', version })).toThrow('already')
  expect(() => writeSystems({ action: 'activate', deployment, confirmation: 'yes' })).toThrow(
    'full deployment'
  )
  writeSystems({ action: 'activate', deployment, confirmation: deployment })
  expect(readSystems('bitcoin').commands).toEqual([expect.objectContaining({ status: 'queued' })])
  expect(readSystems('bitcoin').deployments[0].mode).toBe('shadow')
})
test('address requests are queued for checksum validation, not immediately sent externally', () => {
  writeSystems({
    action: 'watch',
    address: '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa',
    label: 'Research',
  })
  expect(readBitcoin().addresses).toEqual([])
  expect(readBitcoin().requests[0].status).toBe('queued')
  expect(() => writeSystems({ action: 'watch', address: 'private words' })).toThrow('mainnet')
})
test('operator sessions require a strong configured secret and reject tampering', () => {
  process.env.SYSTEMS_OPERATOR_TOKEN = 'short'
  expect(login('short')).toBeNull()
  process.env.SYSTEMS_OPERATOR_TOKEN = '0123456789abcdef0123456789abcdef'
  expect(login('wrong')).toBeNull()
  const cookie = login(process.env.SYSTEMS_OPERATOR_TOKEN)!
  const request = (value: string) =>
    ({ cookies: { get: () => ({ value }) } }) as unknown as NextRequest
  expect(authenticated(request(cookie))).toBe(true)
  expect(authenticated(request(cookie + 'tampered'))).toBe(false)
  expect(authenticated(request('0.' + cookie.split('.')[1]))).toBe(false)
})
