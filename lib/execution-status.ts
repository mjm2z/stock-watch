import 'server-only'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { serverCache } from '@/lib/cache'
import { readExecutionSnapshot } from '@/lib/worker-dashboard'
import { assessExecution, type MarketDay, type TimerHealth } from '@/lib/execution-status-model'
const execute = promisify(execFile)
const units = [ ['Worker','stock-watch-worker'], ['Dispatcher','stock-watch-dispatch'], ['Maintenance','stock-watch-maintenance'], ['Exits','stock-watch-exits'] ] as const
function properties(text: string): Record<string,string> { return Object.fromEntries(text.trim().split('\n').map(line => { const i=line.indexOf('='); return [line.slice(0,i),line.slice(i+1)] })) }
function systemdTime(value?: string): string | null {
  const match = value?.match(/(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) UTC/)
  return match ? `${match[1]}T${match[2]}Z` : null
}
async function readTimers() {
  const cached = serverCache.get<{ timers:TimerHealth[]; nextMaintenance:string|null }>('execution-timers')
  if (cached) return cached
  const rows = await Promise.all(units.map(async ([name,unit]) => {
    try {
      const { stdout } = await execute('/usr/bin/systemctl', ['show',`${unit}.timer`,`${unit}.service`, '--property=Id,LoadState,ActiveState,Result,ExecMainStatus,ExecMainExitTimestamp,NextElapseUSecRealtime'], { timeout:2500, maxBuffer:32768, env:{...process.env,TZ:'UTC'} })
      const groups = stdout.trim().split(/\n\s*\n/).map(properties)
      const timer = groups.find(row => row.Id===unit+'.timer'), service=groups.find(row => row.Id===unit+'.service')
      if (!timer || !service || timer.LoadState!=='loaded' || service.LoadState!=='loaded') throw new Error('Missing service')
      return { name, active:timer.ActiveState==='active', checked:true, lastRun:systemdTime(service.ExecMainExitTimestamp), result:service.Result || 'unknown', exitCode:Number(service.ExecMainStatus), running:['active','activating'].includes(service.ActiveState), next:systemdTime(timer.NextElapseUSecRealtime) }
    } catch { return { name, active:false,checked:false,lastRun:null,result:'unknown',exitCode:null,running:false,next:null } }
  }))
  const result={ timers:rows.map(({next: _next,...row})=>row),nextMaintenance:rows.find(row=>row.name==='Maintenance')?.next ?? null }
  serverCache.set('execution-timers',result,15000)
  return result
}
async function readCalendar(): Promise<MarketDay[] | null> {
  const today = new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
  const key='execution-calendar:'+today
  const cached=serverCache.get<MarketDay[]>(key)
  if (cached) return cached
  if (!process.env.ALPACA_API_KEY_ID || !process.env.ALPACA_API_SECRET_KEY) return null
  try {
    const noon=Date.parse(today+'T12:00:00Z')
    const start=new Date(noon-10*86400000).toISOString().slice(0,10),end=new Date(noon+14*86400000).toISOString().slice(0,10)
    const response=await fetch(`https://paper-api.alpaca.markets/v2/calendar?start=${start}&end=${end}`,{
      headers:{'APCA-API-KEY-ID':process.env.ALPACA_API_KEY_ID,'APCA-API-SECRET-KEY':process.env.ALPACA_API_SECRET_KEY},
      signal:AbortSignal.timeout(5000),cache:'no-store',redirect:'error',
    })
    if (!response.ok) return null
    const result: unknown=await response.json()
    if (!Array.isArray(result) || !result.every(day=>day && typeof day.date==='string' && typeof day.open==='string' && typeof day.close==='string')) return null
    const days=result.map(day=>({date:day.date,open:day.open,close:day.close}))
    serverCache.set(key,days,300000); return days
  } catch { return null }
}
export async function readExecutionStatus() {
  const snapshot=readExecutionSnapshot()
  const [services,calendar]=await Promise.all([readTimers(),readCalendar()])
  return assessExecution(snapshot,services.timers,calendar,Date.now(),services.nextMaintenance)
}
