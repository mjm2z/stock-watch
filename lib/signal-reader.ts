import { Worker } from 'node:worker_threads'
import { resolve } from 'node:path'
import { BoundedCache } from './bounded-cache'
import {
  WorkerDatabaseUnavailable,
  type SignalFilters,
  type readDashboardSignals,
  type readSignalSummary,
} from './worker-dashboard'
type Result = {
  signals: ReturnType<typeof readDashboardSignals>
  summary: ReturnType<typeof readSignalSummary>
}
const cache = new BoundedCache<Result>(8 * 1024 * 1024, 64)
const requests = new Map<string, Promise<Result>>()
type Task = {
  databasePath: string | undefined
  filters: SignalFilters
  resolve: (value: Result) => void
  reject: (error: Error) => void
}
const queue: Task[] = []
const slots: { worker: Worker; busy: boolean }[] = []
function pump() {
  while (queue.length) {
    let slot = slots.find((s) => !s.busy)
    if (!slot && slots.length < 2) {
      const worker = new Worker(
        `
        const { parentPort, workerData } = require('node:worker_threads');
        const reader = require(workerData.modulePath);
        parentPort.on('message', ({filters, databasePath}) => {
          if (databasePath) process.env.STOCK_WATCH_DATABASE_PATH = databasePath; else delete process.env.STOCK_WATCH_DATABASE_PATH;
          try { parentPort.postMessage({ result: { summary: reader.readSignalSummary(filters), signals: reader.readDashboardSignals(filters) } }); }
          catch (e) { parentPort.postMessage({ error: e.message }); }
        });
      `,
        {
          eval: true,
          workerData: {
            modulePath: resolve(process.cwd(), '.signal-worker/lib/worker-dashboard.js'),
          },
        }
      )
      worker.unref()
      slot = { worker, busy: false }
      slots.push(slot)
    }
    if (!slot) return
    const selected = slot,
      task = queue.shift()!
    selected.busy = true
    selected.worker.ref()
    let finished = false
    const finish = (message?: { result?: Result; error?: string }, failure?: Error) => {
      if (finished) return
      finished = true
      clearTimeout(timer)
      selected.worker.removeListener('message', onMessage)
      selected.worker.removeListener('error', onError)
      selected.worker.removeListener('exit', onExit)
      if (failure) {
        void selected.worker.terminate()
        slots.splice(slots.indexOf(selected), 1)
      } else {
        selected.busy = false
        selected.worker.unref()
      }
      if (failure || message?.error)
        task.reject(new WorkerDatabaseUnavailable(failure?.message || message!.error))
      else task.resolve(message!.result!)
      pump()
    }
    const onMessage = (m: { result?: Result; error?: string }) => finish(m)
    const onError = (e: Error) => finish(undefined, e)
    const onExit = () => finish(undefined, new Error('Signal reader exited'))
    const timer = setTimeout(
      () => finish(undefined, new Error('Signal read timed out; retry shortly')),
      15000
    )
    selected.worker.once('message', onMessage).once('error', onError).once('exit', onExit)
    selected.worker.postMessage({ filters: task.filters, databasePath: task.databasePath })
  }
}
export function readSignalsAsync(filters: SignalFilters): Promise<Result> {
  const databasePath = process.env.STOCK_WATCH_DATABASE_PATH
  const key = JSON.stringify([
    databasePath,
    Object.entries(filters).sort(([a], [b]) => a.localeCompare(b)),
  ])
  const hit = cache.get(key)
  if (hit) return Promise.resolve(hit)
  const pending = requests.get(key)
  if (pending) return pending
  if (requests.size >= 16)
    return Promise.reject(new WorkerDatabaseUnavailable('Signals are busy; retry shortly'))
  const task = new Promise<Result>((resolve, reject) => {
    queue.push({ filters, databasePath, resolve, reject })
    pump()
  })
    .then((value) => {
      cache.set(key, value, 15000)
      return value
    })
    .finally(() => requests.delete(key))
  requests.set(key, task)
  return task
}
