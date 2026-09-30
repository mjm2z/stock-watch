/** Diagnostic persistence only: bounded aggregation, isolated from feed delivery. */
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads'
import { DatabaseSync } from 'node:sqlite'

export function retention(path, { intervalMs = 1000, maxMinutes = 120 } = {}) {
  const worker = new Worker(new URL(import.meta.url), { workerData: { path } })
  const pending = new Map()
  let ready = false,
    busy = false,
    failure = null,
    dropped = 0,
    closed = false
  const waiters = []
  const finish = () => {
    if (failure || (!busy && pending.size === 0)) {
      for (const waiter of waiters.splice(0))
        failure ? waiter.reject(new Error(failure)) : waiter.resolve()
    }
  }
  const fail = (error) => {
    if (failure || closed) return
    failure = String(error)
    console.error('Market diagnostic persistence unavailable:', failure)
    finish()
  }
  const pump = () => {
    if (!ready || busy || failure || !pending.size) return finish()
    const batch = [...pending.values()]
    pending.clear()
    busy = true
    worker.postMessage(batch)
  }
  worker.on('message', (message) => {
    if (message.error) return fail(message.error)
    ready = true
    busy = false
    finish()
    if (waiters.length) pump()
  })
  worker.on('error', fail)
  worker.on('exit', (code) => {
    if (!closed) fail(`Persistence worker exited (${code}); restart collector to recover`)
  })
  const timer = setInterval(pump, intervalMs)
  const persist = (snapshot) => {
    if (closed) return
    const minute = Math.floor(snapshot.receivedAt / 60000) * 60000
    let aggregate = pending.get(minute)
    if (!aggregate) {
      if (pending.size >= maxMinutes) {
        pending.delete(pending.keys().next().value)
        dropped++
      }
      aggregate = {
        minute,
        open: snapshot.price,
        high: snapshot.price,
        low: snapshot.price,
        close: snapshot.price,
        observations: 0,
        sourceAge: snapshot.sourceAgeMs,
        processing: Date.now() - snapshot.receivedAt,
        generation: snapshot.generation,
      }
      pending.set(minute, aggregate)
    }
    aggregate.high = Math.max(aggregate.high, snapshot.price)
    aggregate.low = Math.min(aggregate.low, snapshot.price)
    aggregate.close = snapshot.price
    aggregate.observations++
  }
  persist.status = () => ({
    healthy: !failure && dropped === 0,
    error: failure,
    pendingMinutes: pending.size,
    inFlight: busy,
    droppedMinutes: dropped,
  })
  persist.flush = () =>
    new Promise((resolve, reject) => {
      waiters.push({ resolve, reject })
      pump()
    })
  persist.close = async () => {
    clearInterval(timer)
    let deadline
    try {
      await Promise.race([
        persist.flush(),
        new Promise((_, reject) => {
          deadline = setTimeout(() => reject(new Error('Diagnostic flush timed out')), 2000)
        }),
      ])
    } finally {
      clearTimeout(deadline)
      closed = true
      await worker.terminate()
    }
  }
  return persist
}

if (!isMainThread) {
  try {
    const db = new DatabaseSync(workerData.path)
    db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=1000;
      CREATE TABLE IF NOT EXISTS minutes (minute INTEGER PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, observations INTEGER);
      CREATE TABLE IF NOT EXISTS diagnostics (at INTEGER PRIMARY KEY, source_age_ms INTEGER, processing_ms INTEGER, generation TEXT);`)
    const aggregate = db.prepare(`INSERT INTO minutes VALUES (?,?,?,?,?,?) ON CONFLICT(minute)
      DO UPDATE SET high=max(high,excluded.high),low=min(low,excluded.low),
      close=excluded.close,observations=observations+excluded.observations`)
    const diagnostic = db.prepare('INSERT OR IGNORE INTO diagnostics VALUES (?,?,?,?)')
    const pruneMinutes = db.prepare('DELETE FROM minutes WHERE minute < ?')
    const pruneDiagnostics = db.prepare('DELETE FROM diagnostics WHERE at < ?')
    let lastMinute = -1
    parentPort.on('message', (batch) => {
      try {
        db.exec('BEGIN IMMEDIATE')
        let newest = lastMinute
        for (const row of batch) {
          aggregate.run(row.minute, row.open, row.high, row.low, row.close, row.observations)
          diagnostic.run(row.minute, row.sourceAge, row.processing, row.generation)
          newest = Math.max(newest, row.minute)
        }
        if (newest !== lastMinute) {
          pruneMinutes.run(newest - 90 * 86400000)
          pruneDiagnostics.run(newest - 7 * 86400000)
        }
        db.exec('COMMIT')
        lastMinute = newest
        parentPort.postMessage({ ok: true })
      } catch (error) {
        try {
          db.exec('ROLLBACK')
        } catch {
          /* Original error remains authoritative. */
        }
        parentPort.postMessage({ error: error.message })
      }
    })
    parentPort.postMessage({ ready: true })
  } catch (error) {
    parentPort.postMessage({ error: error.message })
  }
}
