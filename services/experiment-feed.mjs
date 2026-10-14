/** One authenticated connection per feed. Credentials never reach the browser. */
import { DatabaseSync } from 'node:sqlite'
import { pathToFileURL } from 'node:url'
const stocks = [
  'SPY',
  'QQQ',
  'IWM',
  'XLF',
  'XLK',
  'XLE',
  'AAPL',
  'MSFT',
  'NVDA',
  'AMZN',
  'GOOGL',
  'META',
  'JPM',
  'XOM',
]
export const timestamp = (value) => new Date(value).toISOString().replace(/(\.\d{3})Z$/, '$1000Z')
export function normalize(message, asset, received = Date.now()) {
  if (
    !['q', 'b', 'u'].includes(message.T) ||
    !(asset === 'stocks' ? stocks : ['BTC/USD']).includes(message.S)
  )
    return null
  const at = Date.parse(message.t)
  if (!Number.isFinite(at) || at > received + 1000 || received - at > 120000)
    throw new Error('Feed timestamp outside receipt window')
  const result = { ...message }
  if (message.T === 'q') {
    if (
      ![message.bp, message.ap, message.bs, message.as].every(Number.isFinite) ||
      message.bp <= 0 ||
      message.ap < message.bp ||
      message.bs < 0 ||
      message.as < 0
    )
      throw new Error('Invalid quote')
    // IEX quote sizes are round lots. Crypto sizes are already asset units.
    result.bid_units = message.bs * (asset === 'stocks' ? 100 : 1)
    result.ask_units = message.as * (asset === 'stocks' ? 100 : 1)
  } else if (
    ![message.o, message.h, message.l, message.c, message.v].every(Number.isFinite) ||
    message.l <= 0 ||
    message.l > Math.min(message.o, message.c) ||
    message.h < Math.max(message.o, message.c) ||
    message.v < 0
  )
    throw new Error('Invalid bar')
  return {
    asset,
    feed: asset === 'stocks' ? 'iex' : 'alpaca-us',
    symbol: message.S,
    kind: message.T,
    at: timestamp(at),
    observed: timestamp(received),
    payload: JSON.stringify(result),
  }
}
export function collector(database, { Socket = WebSocket, now = Date.now } = {}) {
  const db = new DatabaseSync(database)
  db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=3000;
    CREATE TABLE IF NOT EXISTS feed_events (id INTEGER PRIMARY KEY,asset TEXT NOT NULL,feed TEXT NOT NULL,symbol TEXT NOT NULL,kind TEXT NOT NULL,at TEXT NOT NULL,observed TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(asset,feed,symbol,kind,at,observed,payload));
    CREATE INDEX IF NOT EXISTS feed_events_time ON feed_events(asset,feed,symbol,kind,at,observed);
    CREATE TABLE IF NOT EXISTS health(component TEXT PRIMARY KEY,at TEXT NOT NULL,error TEXT);`)
  const insert = db.prepare(
    'INSERT OR IGNORE INTO feed_events(asset,feed,symbol,kind,at,observed,payload) VALUES (?,?,?,?,?,?,?)'
  )
  const lastHealth = new Map()
  const health = (asset, error = null) => {
    if (!error && now() - (lastHealth.get(asset) || 0) < 1000) return
    db.prepare('INSERT OR REPLACE INTO health VALUES (?,?,?)').run(
      'stream:' + asset,
      timestamp(now()),
      error
    )
    lastHealth.set(asset, now())
  }
  let stopping = false
  const sockets = new Set(),
    timers = new Set(),
    pending = new Map()
  const persist = (event) =>
    insert.run(
      event.asset,
      event.feed,
      event.symbol,
      event.kind,
      event.at,
      event.observed,
      event.payload
    )
  function start(asset, retry = 1000) {
    const prefix = asset === 'stocks' ? '' : 'BITCOIN_'
    const key = process.env[prefix + 'ALPACA_API_KEY_ID'],
      secret = process.env[prefix + 'ALPACA_API_SECRET_KEY']
    if (!key || !secret) {
      health(asset, 'Credentials not configured')
      return
    }
    const socket = new Socket(
      asset === 'stocks'
        ? 'wss://stream.data.alpaca.markets/v2/iex'
        : 'wss://stream.data.alpaca.markets/v1beta3/crypto/us'
    )
    sockets.add(socket)
    let authenticated = false,
      lastError = null
    socket.addEventListener('open', () =>
      socket.send(JSON.stringify({ action: 'auth', key, secret }))
    )
    socket.addEventListener('message', ({ data }) => {
      if (stopping) return
      try {
        if (typeof data !== 'string' || data.length > 1048576)
          throw new Error('Unexpected stream payload')
        const rows = JSON.parse(data)
        if (!Array.isArray(rows) || rows.length > 10000) throw new Error('Unbounded stream batch')
        for (const row of rows) {
          if (row.T === 'error')
            throw new Error('Alpaca stream rejected subscription: ' + String(row.code))
          if (row.T === 'success' && row.msg === 'authenticated') {
            authenticated = true
            const symbols = asset === 'stocks' ? stocks : ['BTC/USD']
            socket.send(
              JSON.stringify({
                action: 'subscribe',
                quotes: symbols,
                bars: symbols,
                updatedBars: symbols,
              })
            )
            health(asset)
            retry = 1000
          }
          if (!authenticated) continue
          if (row.T === 'subscription') {
            const symbols = asset === 'stocks' ? stocks : ['BTC/USD']
            if (
              !['quotes', 'bars', 'updatedBars'].every((channel) =>
                symbols.every((symbol) => row[channel]?.includes(symbol))
              )
            )
              throw new Error('Incomplete feed subscription')
          }
          const event = normalize(row, asset, now())
          if (event) {
            if (event.kind === 'q') pending.set(asset + ':' + event.symbol, event)
            else persist(event)
            health(asset)
          }
        }
      } catch (error) {
        lastError = error.message.slice(0, 200)
        health(asset, lastError)
        socket.close()
      }
    })
    socket.addEventListener('error', () => {
      if (!stopping) health(asset, 'Stream disconnected')
    })
    socket.addEventListener('close', () => {
      sockets.delete(socket)
      if (stopping) return
      health(asset, lastError || 'Stream disconnected; retrying')
      if (!stopping) {
        const timer = setTimeout(() => {
          timers.delete(timer)
          start(asset, Math.min(retry * 2, 60000))
        }, retry)
        timers.add(timer)
      }
    })
  }
  // Bound quote IO to one latest observation per symbol/second. Minute bar
  // revisions retain their original receipt times and are never coalesced.
  const flush = setInterval(() => {
    try {
      db.exec('BEGIN IMMEDIATE')
      for (const event of pending.values()) persist(event)
      db.exec('COMMIT')
      pending.clear()
    } catch {
      try {
        db.exec('ROLLBACK')
      } catch {}
    }
  }, 1000)
  start('stocks')
  start('bitcoin')
  return () => {
    stopping = true
    clearInterval(flush)
    for (const t of timers) clearTimeout(t)
    for (const s of sockets) s.close()
    db.close()
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const stop = collector(process.env.STOCK_WATCH_DATABASE_PATH + '.experiment-evidence.db')
  process.once('SIGTERM', stop)
  process.once('SIGINT', stop)
}
