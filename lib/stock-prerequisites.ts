import 'server-only'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { DatabaseSync } from 'node:sqlite'

type InputCounts = {
  universeId: number | null
  instruments: number
  missingSectors: number
  requestedSessions: number
  rawBars: number
  barsWithoutCalendar: number
  usableBars: number
  usableInstruments: number
  coveredStart: string | null
  coveredEnd: string | null
  ambiguousSessions: number
  benchmarkBars: number
}

export const prerequisiteSQL = readFileSync(
  join(process.cwd(), 'worker/src/stock_watch_worker/stock_prerequisites.sql'),
  'utf8'
)
const quality = JSON.parse(
  readFileSync(join(process.cwd(), 'worker/src/stock_watch_worker/stock_capabilities.json'), 'utf8')
)

export function stockPrerequisites(db: DatabaseSync, start: string, end: string) {
  return stockPrerequisiteReport(
    db.prepare(prerequisiteSQL).get({ start, end }) as unknown as InputCounts
  )
}

export function stockPrerequisiteReport(row: InputCounts) {
  const blockers: string[] = []
  if (!row.instruments) blockers.push('No captured stock universe members')
  if (!row.rawBars)
    blockers.push('Raw daily bars are missing; adjusted scanner bars cannot substitute')
  if (!row.requestedSessions)
    blockers.push('No captured exchange sessions cover this requested interval')
  if (row.instruments && row.missingSectors === row.instruments)
    blockers.push('Sector metadata is missing for all universe members')
  if (row.ambiguousSessions)
    blockers.push(
      'Multiple raw daily sources cover the same symbol/session; select a canonical source'
    )
  if (!row.usableBars)
    blockers.push('No raw bars join sector and calendar data in this requested interval')
  return {
    ...row,
    blockers,
    canPrepare: blockers.length === 0,
    quality,
    note: 'Input presence is not qualification. Coverage can be partial; per-system warmup and evaluation-window sufficiency are not certified here. Corporate actions and historical membership remain unverified.',
  }
}
