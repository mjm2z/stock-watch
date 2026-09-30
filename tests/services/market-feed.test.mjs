import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Feed, serve, retention, writeSnapshot } from '../../services/market-feed.mjs'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
const message = (seq, price, at, channel = 'ticker') => ({
  channel,
  sequence_num: seq,
  timestamp: new Date(at).toISOString(),
  events: [{ tickers: [{ product_id: 'BTC-USD', price: String(price) }] }],
})
test('every distinct price, duplicate values, stale and new generation', () => {
  let now = 10000
  const feed = new Feed({ now: () => now })
  const seen = []
  feed.listeners.add((s) => seen.push(s))
  feed.connect()
  feed.accept(message(0, 0, now, 'heartbeats'))
  feed.accept(message(1, 100, now))
  feed.accept(message(2, 101, now))
  feed.accept(message(3, 102, now))
  feed.accept(message(4, 102, now))
  assert.deepEqual(
    seen.filter((s) => s.price).map((s) => s.price),
    [100, 101, 102]
  )
  assert.equal(feed.snapshot().fresh, true)
  now += 3001
  assert.equal(feed.snapshot().fresh, false)
  const generation = feed.generation
  feed.disconnect()
  feed.connect()
  assert.notEqual(feed.generation, generation)
  assert.equal(feed.price, 102)
  assert.equal(feed.snapshot().fresh, false)
})
test('gaps, out of order, invalid and stale events fail closed', () => {
  for (const bad of [
    message(0, 100, 10000),
    message(3, 100, 10000),
    message(1, 'NaN', 10000),
    message(1, 100, 1000),
  ]) {
    const feed = new Feed({ now: () => 10000 })
    feed.connect()
    feed.accept(message(0, 100, 10000))
    assert.throws(() => feed.accept(bad))
    assert.equal(feed.snapshot().fresh, false)
  }
})
test('SSE begins with current snapshot and closes listener on disconnect', async () => {
  const feed = new Feed()
  const server = serve(feed, 0)
  await new Promise((resolve) => server.once('listening', resolve))
  const controller = new AbortController()
  try {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/events`, {
      signal: controller.signal,
    })
    const reader = response.body.getReader()
    const first = await reader.read()
    assert.match(new TextDecoder().decode(first.value), /Reconnecting/)
    assert.equal(feed.listeners.size, 1)
    controller.abort()
    await reader.cancel().catch(() => {})
    await new Promise((resolve) => setTimeout(resolve, 50))
    assert.equal(feed.listeners.size, 0)
  } finally {
    server.closeAllConnections()
    server.close()
  }
})
test('retention bounds minute aggregates and diagnostics independently', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'feed-'))
  const path = join(directory, 'db')
  try {
    const persist = retention(path)
    for (const day of [0, 1, 91])
      persist({ receivedAt: day * 86400000, price: 100, sourceAgeMs: 1, generation: 'g' })
    await persist.close()
    const db = new DatabaseSync(path)
    assert.equal(db.prepare('SELECT count(*) n FROM minutes').get().n, 2)
    assert.equal(db.prepare('SELECT count(*) n FROM diagnostics').get().n, 1)
    db.close()
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

test('blocked diagnostic writes do not block ticks; batches retain exact OHLC and counts', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'feed-batched-'))
  const path = join(directory, 'db')
  const persist = retention(path, { intervalMs: 60000 })
  let db
  try {
    const now = Date.now()
    persist({ receivedAt: now, price: 100, sourceAgeMs: 0, generation: 'g' })
    await persist.flush()
    db = new DatabaseSync(path)
    db.exec('BEGIN IMMEDIATE')
    const feed = new Feed({ now: () => now, persist })
    const prices = []
    feed.listeners.add((s) => {
      if (s.price !== null) prices.push(s.price)
    })
    feed.connect()
    feed.accept(message(0, 0, now, 'heartbeats'))
    for (let i = 1; i <= 100; i++) feed.accept(message(i, i + 100, now))
    const flushed = persist.flush()
    assert.equal(prices.length, 100)
    // Main-thread timer must execute while the SQLite worker waits for its lock.
    await new Promise((resolve) => setTimeout(resolve, 50))
    db.exec('COMMIT')
    await flushed
    const row = db.prepare('SELECT * FROM minutes').get()
    assert.deepEqual(
      [row.open, row.high, row.low, row.close, row.observations],
      [100, 200, 100, 200, 101]
    )
  } finally {
    if (db) {
      try {
        db.exec('ROLLBACK')
      } catch {}
      db.close()
    }
    await persist.close()
    rmSync(directory, { recursive: true, force: true })
  }
})

test('diagnostic backlog is bounded and reports dropped minutes', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'feed-bounded-'))
  const persist = retention(join(directory, 'db'), { intervalMs: 60000, maxMinutes: 2 })
  try {
    for (let minute = 0; minute < 1000; minute++)
      persist({ receivedAt: minute * 60000, price: 100, sourceAgeMs: 0, generation: 'g' })
    assert.equal(persist.status().pendingMinutes, 2)
    assert.equal(persist.status().droppedMinutes, 998)
    assert.equal(persist.status().healthy, false)
  } finally {
    await persist.close()
    rmSync(directory, { recursive: true, force: true })
  }
})

test('slow clients are disconnected before adding unbounded queued events', () => {
  let destroyed = false,
    writes = 0
  writeSnapshot(
    {
      writableLength: 65537,
      destroy() {
        destroyed = true
      },
      write() {
        writes++
      },
    },
    { id: '1' }
  )
  assert.equal(destroyed, true)
  assert.equal(writes, 0)
})
test('subscription acknowledgements participate in global sequence checks', () => {
  const feed = new Feed({ now: () => 10000 })
  feed.connect()
  feed.accept(message(0, 100, 10000))
  feed.accept({ channel: 'subscriptions', sequence_num: 1 })
  feed.accept(message(2, 0, 10000, 'heartbeats'))
  feed.accept(message(3, 101, 10000))
  assert.equal(feed.snapshot().fresh, true)
})
