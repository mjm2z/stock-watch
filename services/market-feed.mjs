/** Coinbase observations only. No credentials or order submission capability. */
import { createServer } from 'node:http'
import { DatabaseSync } from 'node:sqlite'
import { randomUUID } from 'node:crypto'
import { pathToFileURL } from 'node:url'

export class Feed {
  constructor({ now = Date.now, persist = () => {} } = {}) {
    this.now = now
    this.persist = persist
    this.listeners = new Set()
    this.generation = randomUUID()
    this.serial = 0
    this.sequences = new Map()
    this.price = null
    this.sourceAt = null
    this.receivedAt = null
    this.heartbeatAt = 0
    this.connected = false
    this.valid = false
  }
  snapshot() {
    const now = this.now()
    const age = this.sourceAt === null ? null : now - Date.parse(this.sourceAt)
    const fresh =
      this.connected &&
      this.valid &&
      this.heartbeatAt > 0 &&
      now - this.heartbeatAt <= 3000 &&
      age !== null &&
      age >= -1000 &&
      age <= 5000 &&
      now - this.receivedAt <= 5000
    return {
      id: `${this.generation}:${this.serial}`,
      generation: this.generation,
      source: 'Coinbase Advanced Trade ticker',
      product: 'BTC-USD',
      price: this.price,
      sourceAt: this.sourceAt,
      receivedAt: this.receivedAt,
      heartbeatAt: this.heartbeatAt,
      sourceAgeMs: age,
      fresh,
      status: fresh ? 'Live' : this.connected ? 'Stale' : 'Reconnecting',
    }
  }
  publish() {
    this.serial++
    const snapshot = this.snapshot()
    for (const listener of this.listeners) listener(snapshot)
  }
  connect() {
    this.generation = randomUUID()
    this.sequences.clear()
    this.heartbeatAt = 0
    this.valid = false
    this.connected = true
    this.publish()
  }
  disconnect() {
    this.connected = false
    this.valid = false
    this.publish()
  }
  accept(message) {
    const seq = message.sequence_num
    const last = this.sequences.get('connection')
    if (!Number.isSafeInteger(seq) || (last !== undefined && seq !== last + 1)) {
      this.valid = false
      this.publish()
      throw new Error('Sequence discontinuity')
    }
    this.sequences.set('connection', seq)
    if (!['ticker', 'heartbeats'].includes(message.channel)) return
    const timestamp = Date.parse(message.timestamp)
    if (
      !Number.isFinite(timestamp) ||
      this.now() - timestamp > 5000 ||
      timestamp - this.now() > 1000 ||
      (message.channel === 'ticker' && this.sourceAt && timestamp < Date.parse(this.sourceAt))
    ) {
      this.valid = false
      this.publish()
      throw new Error('Invalid source timestamp')
    }
    if (message.channel === 'heartbeats') {
      this.heartbeatAt = this.now()
      this.publish()
      return
    }
    for (const event of message.events || [])
      for (const ticker of event.tickers || []) {
        if (ticker.product_id !== 'BTC-USD') continue
        const price = Number(ticker.price)
        if (!Number.isFinite(price) || price <= 0) {
          this.valid = false
          this.publish()
          throw new Error('Invalid price')
        }
        const changed = this.price !== price
        const wasFresh = this.snapshot().fresh
        this.price = price
        this.sourceAt = message.timestamp
        this.receivedAt = this.now()
        this.valid = true
        if (changed || !wasFresh) this.publish()
        this.persist(this.snapshot())
      }
  }
}

export function retention(path) {
  const db = new DatabaseSync(path)
  db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=1000;
    CREATE TABLE IF NOT EXISTS minutes (minute INTEGER PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, observations INTEGER);
    CREATE TABLE IF NOT EXISTS diagnostics (at INTEGER PRIMARY KEY, source_age_ms INTEGER, processing_ms INTEGER, generation TEXT);`)
  let lastMinute = -1
  return (snapshot) => {
    const minute = Math.floor(snapshot.receivedAt / 60000) * 60000
    db.prepare(
      `INSERT INTO minutes VALUES (?,?,?,?,?,1) ON CONFLICT(minute) DO UPDATE SET high=max(high,excluded.high),low=min(low,excluded.low),close=excluded.close,observations=observations+1`
    ).run(minute, snapshot.price, snapshot.price, snapshot.price, snapshot.price)
    if (minute !== lastMinute) {
      lastMinute = minute
      db.prepare('INSERT OR REPLACE INTO diagnostics VALUES (?,?,?,?)').run(
        minute,
        snapshot.sourceAgeMs,
        Date.now() - snapshot.receivedAt,
        snapshot.generation
      )
      db.prepare('DELETE FROM minutes WHERE minute < ?').run(minute - 90 * 86400000)
      db.prepare('DELETE FROM diagnostics WHERE at < ?').run(minute - 7 * 86400000)
    }
  }
}

export function writeSnapshot(res, snapshot) {
  if (res.writableLength > 65536) {
    res.destroy()
    return
  }
  res.write(`id: ${snapshot.id}\ndata: ${JSON.stringify(snapshot)}\n\n`)
}

export function serve(feed, port = 3012) {
  const clients = new Set()
  const server = createServer((req, res) => {
    if (req.method !== 'GET') {
      res.writeHead(405).end()
      return
    }
    if (req.url === '/snapshot' || req.url === '/health') {
      const snapshot = feed.snapshot()
      res.writeHead(req.url === '/health' && !snapshot.fresh ? 503 : 200, {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store',
      })
      res.end(JSON.stringify(snapshot))
      return
    }
    if (req.url !== '/events') {
      res.writeHead(404).end()
      return
    }
    if (clients.size >= 128) {
      res.writeHead(503).end()
      return
    }
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-store',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    })
    const listener = (snapshot) => {
      // A slow client reconnects to a new snapshot; never accumulate tick queues.
      writeSnapshot(res, snapshot)
    }
    clients.add(res)
    feed.listeners.add(listener)
    listener(feed.snapshot())
    res.on('close', () => {
      clients.delete(res)
      feed.listeners.delete(listener)
    })
  })
  server.listen(port, '127.0.0.1')
  return server
}

export function collect(feed) {
  let stopped = false,
    socket,
    retry,
    attempt = 0,
    openedAt = 0,
    lastStatus = ''
  const connect = () => {
    if (stopped) return
    socket = new WebSocket('wss://advanced-trade-ws.coinbase.com')
    const deadline = setTimeout(() => socket.close(), 10000)
    socket.addEventListener('open', () => {
      clearTimeout(deadline)
      openedAt = Date.now()
      feed.connect()
      for (const channel of ['ticker', 'heartbeats'])
        socket.send(JSON.stringify({ type: 'subscribe', product_ids: ['BTC-USD'], channel }))
    })
    socket.addEventListener('message', (event) => {
      try {
        feed.accept(JSON.parse(event.data))
        if (feed.snapshot().fresh) attempt = 0
      } catch {
        socket.close()
        feed.disconnect()
      }
    })
    socket.addEventListener('error', () => socket.close())
    socket.addEventListener('close', () => {
      clearTimeout(deadline)
      feed.disconnect()
      if (!stopped)
        retry = setTimeout(
          connect,
          Math.min(30000, 500 * 2 ** Math.min(attempt++, 6)) * (0.75 + Math.random() * 0.5)
        )
    })
  }
  // Freshness timers publish state changes only; prices are forwarded synchronously.
  const freshness = setInterval(() => {
    const snapshot = feed.snapshot()
    if (snapshot.status !== lastStatus) {
      lastStatus = snapshot.status
      feed.publish()
    }
    if (
      feed.connected &&
      (feed.heartbeatAt ? feed.now() - feed.heartbeatAt > 3000 : Date.now() - openedAt > 10000)
    )
      socket?.close()
  }, 250)
  connect()
  return () => {
    stopped = true
    clearTimeout(retry)
    clearInterval(freshness)
    socket?.close()
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const feed = new Feed({
    persist: retention(
      process.env.STOCK_WATCH_MARKET_DATABASE || '/var/lib/stock-watch/market-data.db'
    ),
  })
  const server = serve(feed)
  const stop = collect(feed)
  for (const signal of ['SIGTERM', 'SIGINT'])
    process.on(signal, () => {
      stop()
      server.closeAllConnections()
      server.close()
    })
}
