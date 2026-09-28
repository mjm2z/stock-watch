import 'server-only'
import { Worker } from 'node:worker_threads'
import { existsSync, statSync } from 'node:fs'
import { stockPrerequisiteReport, prerequisiteSQL } from './stock-prerequisites'

type Report = ReturnType<typeof stockPrerequisiteReport>
type Entry = { at: number; revision: string; report?: Report; error?: string; worker?: Worker }
const entries = new Map<string, Entry>()
const ttl = 60_000
const script = `const {parentPort,workerData}=require('node:worker_threads');
const {DatabaseSync}=require('node:sqlite');
const db=new DatabaseSync(workerData.path,{readOnly:true});
try { db.exec('PRAGMA busy_timeout=1000'); parentPort.postMessage(db.prepare(workerData.sql).get({start:workerData.start,end:workerData.end})); }
finally { db.close(); }`
export function stockPreflight(start: string, end: string) {
  const path = process.env.STOCK_WATCH_DATABASE_PATH || ''
  if (!path || !existsSync(path)) throw new Error('Stock data prerequisites are unavailable.')
  const revision = [path, path + '-wal']
    .map((p) => {
      try {
        const s = statSync(p)
        return `${s.size}:${s.mtimeMs}`
      } catch {
        return '-'
      }
    })
    .join('|')
  const key = JSON.stringify([path, start, end])
  let entry = entries.get(key)
  if (!entry || (!entry.worker && Date.now() - entry.at >= ttl)) {
    if (entry?.report && entry.revision === revision) entry.at = Date.now()
    else {
      if ([...entries.values()].filter((e) => e.worker).length >= 2)
        return {
          state: 'checking',
          canPrepare: false,
          blockers: ['Waiting for an inspection slot.'],
        }
      if (entries.size >= 32)
        for (const [old, value] of entries) {
          if (!value.worker) {
            entries.delete(old)
            break
          }
        }
      entry = { at: Date.now(), revision, report: entry?.report }
      entries.set(key, entry)
      const current = entry
      const worker = new Worker(script, {
        eval: true,
        workerData: { path, sql: prerequisiteSQL, start, end },
      })
      current.worker = worker
      const timer = setTimeout(() => {
        current.error = 'Inspection timed out.'
        void worker.terminate()
      }, 120000)
      worker.once('message', (row) => {
        current.report = stockPrerequisiteReport(row)
        current.error = undefined
        current.at = Date.now()
      })
      worker.once('error', () => {
        current.error = 'Stock data inspection is unavailable.'
      })
      worker.once('exit', () => {
        clearTimeout(timer)
        current.worker = undefined
        current.at = Date.now()
      })
    }
  }
  if (entry.worker)
    return {
      ...entry.report,
      state: entry.report ? 'stale' : 'checking',
      canPrepare: false,
      blockers: ['Checking captured data for this interval…'],
    }
  if (entry.error)
    return { state: 'unavailable', canPrepare: false, error: entry.error, blockers: [entry.error] }
  return {
    ...entry.report,
    state: 'ready',
    checkedAt: new Date(entry.at).toISOString(),
    inputRevision: entry.revision,
  }
}
