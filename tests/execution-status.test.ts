import { assessExecution, calendarWindows, type ExecutionSnapshot, type TimerHealth } from '@/lib/execution-status-model'
const now=Date.parse('2026-09-17T18:00:00Z')
const days=[{date:'2026-09-17',open:'09:30',close:'16:00'},{date:'2026-09-18',open:'09:30',close:'16:00'}]
const snapshot:ExecutionSnapshot={strategyId:'paper-v1',strategyStatus:'paper',strategySince:'2026-09-17T17:15:00Z',credentialsConfigured:true,
  latestScan:null,lastSuccess:null,lastScheduledSuccess:null,reconciliation:{status:'matched',at:'2026-09-17T17:15:00Z'},ingestions:[]}
const timers:TimerHealth[]=['Worker','Dispatcher','Maintenance','Exits'].map(name=>({name,active:true,checked:true,lastRun:'2026-09-17T17:59:00Z',result:'success',exitCode:0,running:false}))
test('exchange calendar handles early closes, DST and holiday gaps',()=>{
  expect(calendarWindows([{date:'2026-11-27',open:'09:30',close:'13:00'},{date:'2026-09-17',open:'09:30',close:'16:00'}])).toEqual([
    {type:'open',at:'2026-09-17T13:45:00.000Z'},{type:'close',at:'2026-09-17T20:15:00.000Z'},
    {type:'open',at:'2026-11-27T14:45:00.000Z'},{type:'close',at:'2026-11-27T18:15:00.000Z'},
  ])
})
test('newly promoted strategy is not blamed for scans before promotion',()=>{
  const result=assessExecution(snapshot,timers,days,now)
  expect(result.state).toBe('ready');expect(result.nextScan?.at).toBe('2026-09-17T20:15:00.000Z')
})
test('stopped timers block readiness and unknown service state never looks ready',()=>{
  expect(assessExecution(snapshot,[{...timers[0],active:false}],days,now).state).toBe('blocked')
  expect(assessExecution(snapshot,[{...timers[0],checked:false}],days,now).state).toBe('unknown')
  expect(assessExecution(snapshot,timers,null,now).state).toBe('unknown')
})
test('stale worker and failed scheduler run surface issues',()=>{
  const result=assessExecution(snapshot,[{...timers[0],lastRun:'2026-09-17T16:00:00Z',result:'exit-code',exitCode:1}],days,now)
  expect(result.state).toBe('attention');expect(result.issues.join(' ')).toMatch(/last run failed.*no recent/)
})
test('past-due scan remains visible instead of silently moving countdown to tomorrow',()=>{
  const after=Date.parse('2026-09-17T20:40:00Z')
  const healthy=timers.map(timer=>({...timer,lastRun:'2026-09-17T20:39:00Z'}))
  const result=assessExecution(snapshot,healthy,days,after)
  expect(result.state).toBe('attention');expect(result.issues.join(' ')).toContain('most recent scheduled scan')
  expect(result.nextScan?.at).toBe('2026-09-18T13:45:00.000Z')
})
test('due window reports waiting and active scans report running',()=>{
  const due=Date.parse('2026-09-17T20:16:00Z'), healthy=timers.map(t=>({...t,lastRun:'2026-09-17T20:15:30Z'}))
  expect(assessExecution(snapshot,healthy,days,due).issues.join(' ')).toContain('due now')
  expect(assessExecution({...snapshot,latestScan:{id:'s',type:'close',at:'2026-09-17T20:15:00Z',completedAt:null,status:'running',strategyId:'paper-v1',error:null}},healthy,days,due).state).toBe('running')
})
test('broker mismatch blocks and missing configuration is unknown',()=>{
  expect(assessExecution({...snapshot,reconciliation:{status:'mismatch',at:'2026-09-17T18:00:00Z'}},timers,days,now).state).toBe('blocked')
  expect(assessExecution({...snapshot,strategyId:null},timers,days,now).state).toBe('unknown')
})

test('exit scheduler must stay active and recent',()=>{
  const exits=timers.find(timer=>timer.name==='Exits')!
  expect(assessExecution(snapshot,[{...exits,active:false}],days,now).state).toBe('blocked')
  const stale=assessExecution(snapshot,[{...exits,lastRun:'2026-09-17T17:50:00Z'}],days,now)
  expect(stale.issues).toContain('Exits: no recent completed check.')
})
