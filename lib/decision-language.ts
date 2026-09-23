import { formatCurrency } from '@/lib/utils'

const reasons: Record<string, string> = {
  portfolio_notional_limit: 'The $300 portfolio allocation limit would be exceeded',
  sector_notional_limit: 'The $60 sector allocation limit would be exceeded',
  unclassified_sector_limit: 'The $60 shared Unknown-sector limit would be exceeded',
  waiting_for_regular_session: 'Waiting for the next trading session and a fresh quote',
  waiting_for_scheduled_check: 'Waiting for the scheduled entry check',
  signal_expired: 'Entry window expired; reserved allocation was released',
  spread_too_wide: 'Waiting: bid–ask spread exceeds 1%',
  stale_quote: 'Waiting: quote is too old or has a future timestamp',
  entry_price_moved: 'Entry canceled: price moved more than 5% from the assessment price',
  insufficient_unreserved_cash: 'Entry canceled: insufficient cash after pending commitments',
  earnings_window: 'Entry canceled: within the known earnings-event buffer',
  entry_verification_unavailable: 'Waiting: entry verification could not be completed',
  entry_checks_passed: 'Entry checks passed; sent to the paper broker',
  data_review_unavailable: 'Entry blocked: input-quality review is unavailable',

  not_in_universe: 'Outside the strategy’s stock universe',
  score_below_threshold: 'Ranking score is below the minimum',
  insufficient_data: 'Not enough scoring data is available',
  risk_not_allowed: 'Risk exceeds the strategy’s allowed level',
  strategy_not_promoted_to_paper: 'Research-only strategy; paper orders are disabled',
  signal_not_qualified: 'Signal did not pass qualification checks',
  instrument_inactive: 'Stock is not currently active for trading',
  instrument_not_fractionable: 'Broker does not support fractional orders for this stock',
  duplicate_open_lot: 'A position already exists for this stock and holding period',
  ticker_notional_limit: 'The per-stock investment limit would be exceeded',
  broker_reconciliation_unavailable: 'Broker positions have not been checked yet',
  broker_position_drift: 'Broker positions differ from the app’s records',
  broker_reconciliation_stale: 'Broker positions need a newer check before an order can be placed',
  missing_calendar: 'Waiting for the exchange calendar',
  waiting_for_horizon: 'Waiting for the full holding-period calendar',
  waiting_for_close: 'Waiting for the holding period to finish',
  missing_fresh_data: 'Waiting for verified closing prices',
  completed: 'Evaluation complete',
}
export function decisionReason(value: string): string {
  return reasons[value] ?? value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase())
}
export function decisionExplanation(value: string, codes: string[]): string {
  return codes.reduce((text, code) => text.replaceAll(code, decisionReason(code)), value)
}
const eventNames: Record<string, string> = {
  paper_entry_check: 'Entry conditions checked',
  paper_order_intent_rejected: 'Paper order blocked',
  paper_order_intent_created: 'Paper order prepared',
  paper_order_reconciled: 'Broker order checked',
  paper_exit_intent_created: 'Exit order prepared',
  paper_exit_reconciled: 'Broker exit checked',
  signal_outcome_completed: 'Research outcome measured',
}
export function decisionEvent(value: string): string { return eventNames[value] ?? decisionReason(value) }
export function eventDetails(detail: string): string {
  let payload: unknown
  try { payload = JSON.parse(detail) } catch { return decisionReason(detail) }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return 'Event recorded'
  const fields = payload as Record<string, unknown>
  const parts: string[] = []
  if (typeof fields.reason === 'string') parts.push(decisionReason(fields.reason))
  if (typeof fields.status === 'string') parts.push(`Status: ${decisionReason(fields.status)}`)
  if (typeof fields.notional_usd === 'number') parts.push(`Investment: ${formatCurrency(fields.notional_usd)}`)
  if (typeof fields.quantity === 'number') parts.push(`${fields.quantity.toLocaleString('en-US', { maximumFractionDigits: 6 })} shares`)
  if (typeof fields.net_return === 'number') parts.push(`Net return: ${(fields.net_return * 100).toFixed(2)}%`)
  if (typeof fields.beat_spy === 'boolean') parts.push(fields.beat_spy ? 'Outperformed SPY' : 'Did not outperform SPY')
  if (typeof fields.entry_session === 'string' && typeof fields.exit_session === 'string') parts.push(`Holding window: ${fields.entry_session} to ${fields.exit_session}`)
  return parts.join(' · ') || 'Event recorded; identifiers are available in technical details'
}
