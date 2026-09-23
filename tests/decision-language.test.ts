import { decisionReason, decisionExplanation, eventDetails } from '@/lib/decision-language'
test('explains risk and order blockers without dropping unknown future codes',()=>{
  expect(decisionReason('risk_not_allowed')).toContain('Risk exceeds')
  expect(decisionReason('new_future_reason')).toBe('New future reason')
  expect(decisionExplanation('Rejected: risk_not_allowed.',['risk_not_allowed'])).toBe('Rejected: Risk exceeds the strategy’s allowed level.')
})
test('formats recorded financial event fields without raw JSON or floating-point noise',()=>{
  expect(eventDetails('{"net_return":0.09900000000000009,"beat_spy":true}')).toBe('Net return: 9.90% · Outperformed SPY')
  expect(eventDetails('{"notional_usd":10,"status":"partially_filled"}')).toBe('Status: Partially filled · Investment: $10.00')
  expect(eventDetails('strategy_not_promoted_to_paper')).toContain('Research-only')
  expect(eventDetails('null')).toBe('Event recorded')
})
