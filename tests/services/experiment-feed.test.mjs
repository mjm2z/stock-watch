import test from 'node:test'
import assert from 'node:assert/strict'
import { normalize, timestamp } from '../../services/experiment-feed.mjs'
const now = Date.parse('2026-10-14T14:05:35.100Z')
test('quote quantities normalize round lots only on the stock feed', () => {
  const quote = { T: 'q', S: 'SPY', t: new Date(now).toISOString(), bp: 100, ap: 101, bs: 2, as: 3 }
  const stock = normalize(quote, 'stocks', now),
    crypto = normalize({ ...quote, S: 'BTC/USD' }, 'bitcoin', now)
  assert.equal(JSON.parse(stock.payload).bid_units, 200)
  assert.equal(JSON.parse(crypto.payload).bid_units, 2)
  assert.equal(stock.observed, '2026-10-14T14:05:35.100000Z')
  assert.equal(timestamp(now), '2026-10-14T14:05:35.100000Z')
})
test('invalid prices, unknown symbols and stale events never become evidence', () => {
  assert.equal(normalize({ T: 'q', S: 'UNKNOWN' }, 'stocks', now), null)
  assert.throws(
    () =>
      normalize(
        { T: 'q', S: 'SPY', t: new Date(now).toISOString(), bp: 101, ap: 100, bs: 2, as: 3 },
        'stocks',
        now
      ),
    /Invalid quote/
  )
  assert.throws(
    () =>
      normalize(
        {
          T: 'b',
          S: 'SPY',
          t: new Date(now - 180000).toISOString(),
          o: 100,
          h: 101,
          l: 99,
          c: 100,
          v: 2,
        },
        'stocks',
        now
      ),
    /timestamp/
  )
})
