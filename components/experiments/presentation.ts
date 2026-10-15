export type Asset = 'stocks' | 'bitcoin'
export type Version = {
  family: string
  universe: string[]
  allocation?: string
  holding_minutes: number
  stop: string
  take: string
  trend_fast?: number
  breakout_period?: number
  rsi_entry?: number
}
export type Batch = {
  id: string
  revision: string
  status: string
  created?: string
  equity: string
  expires: string
  risk_reason: string | null
  plan: { versions: Version[] }
}
export type Instance = {
  id: string
  batch_id: string
  family: string
  budget: string
  cash: string
  state: string
  paused?: number
  reason: string | null
  last_decision: string | null
}
export type ExperimentData = {
  context: {
    id: string
    source: string
    symbol: string | null
    title: string
    url: string
    published: string
    observed: string
  }[]
  proposals: { id: string; family: string; variant: number; week: string; evidence_json?: string }[]
  batches: Batch[]
  instances: Instance[]
  health: { component: string; at: string; error: string | null }[]
  commands: {
    id: string
    action: string
    status: string
    result_json: string | null
    created?: string
  }[]
  research: {
    id: string
    status: string
    result_json: string | null
    error: string | null
    created_at?: string
  }[]
}
export type Decision = {
  id: string
  symbol: string
  cutoff: string
  outcome: string
  reason: string
  evidence: {
    conditions?: { left: number; op: string; right: number }[]
    bars?: number[]
    news?: unknown[]
  }
}
export type Detail = {
  gaps: { start: string; end: string; reason: string }[]
  decisions: Decision[]
  next: string | null
  positions: { symbol: string; quantity: string; cost: string; exit_due: string | null }[]
  orders: {
    id: string
    symbol: string
    side: string
    status: string
    filled_qty: string
    error: string | null
  }[]
}
export type Command = (action: string, extra?: Record<string, string>) => Promise<void>
export const families = ['trend', 'breakout', 'reversal', 'news_breakout', 'control']
const catalog: Record<string, { title: string; description: string }> = {
  trend: { title: 'Trend following', description: 'Follow an established upward price trend.' },
  breakout: {
    title: 'Price breakout',
    description: 'Look for price moving above its recent range.',
  },
  reversal: {
    title: 'Momentum recovery',
    description: 'Look for recovering momentum within an uptrend.',
  },
  news_breakout: {
    title: 'News breakout',
    description: 'Pair a price breakout with timely, symbol-linked news.',
  },
  control: {
    title: 'Daily control',
    description: 'A small scheduled trade to check the full execution path.',
  },
}
export const human = (value: string | null | undefined) => value?.replaceAll('_', ' ') || '—'
export const family = (name: string) =>
  catalog[name] || { title: human(name), description: 'A paper experiment with fixed rules.' }
export const amount = (value: string | number) =>
  Number(value).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  })
export const percent = (value: string | number) => `${Number((Number(value) * 100).toFixed(2))}%`
export const date = (value?: string | null) =>
  value ? new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—'
export const when = (value?: string | null) =>
  value
    ? new Date(value).toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      })
    : 'No decisions yet'
export const duration = (minutes: number) =>
  minutes >= 60 ? `${minutes / 60} hr` : `${minutes} min`
export function parsed<T>(value: string | null | undefined, fallback: T): T {
  try {
    return value ? (JSON.parse(value) as T) : fallback
  } catch {
    return fallback
  }
}
const reasons: Record<string, string> = {
  waiting_signal: 'Waiting for a qualifying signal.',
  market_closed: 'Waiting for the market to open.',
  outside_entry_session: 'Outside the entry window.',
  waiting_news: 'Waiting for recent news to confirm the breakout.',
  fee_attribution_pending: 'Waiting for broker fees to reconcile.',
  account_cash_mismatch: 'Account cash needs reconciliation.',
  missed_entry_window: 'The entry window passed. Waiting for the next opportunity.',
  batch_expired: 'This batch has finished its trading period.',
  operator_pause: 'New entries are paused. Existing exits remain monitored.',
  exits_continue: 'Closing owned positions.',
  pool_drawdown_limit: 'The pool reached its drawdown limit.',
  daily_pool_loss_limit: 'The pool reached its daily loss limit.',
  entry_order_pending: 'Waiting for an entry order to fill.',
}
export const reason = (value: string | null) =>
  value?.startsWith('collecting')
    ? 'Collecting enough price history to evaluate.'
    : reasons[value || ''] || human(value)
export const stateLabel = (value: string) =>
  ({
    waiting_signal: 'Watching',
    collecting: 'Collecting data',
    ready: 'Ready',
    blocked: 'Needs attention',
    exiting: 'Exiting',
    paused: 'Paused',
    expired: 'Expired',
    completed: 'Completed',
    preview: 'Awaiting approval',
    active: 'Running',
    succeeded: 'Completed',
    pending: 'Queued',
    failed: 'Failed',
  })[value] || human(value)
export function rules(version: Version) {
  const fast = version.trend_fast || 20
  if (version.family === 'trend')
    return {
      entry: `EMA${fast} above EMA50, with price above EMA${fast}.`,
      exit: `Price falls below EMA${fast}.`,
    }
  if (version.family === 'reversal')
    return {
      entry: `RSI14 crosses above ${version.rsi_entry || 35}, with price above EMA50.`,
      exit: 'RSI reaches 55, or price falls below EMA50.',
    }
  if (version.family === 'control')
    return {
      entry: '$10 at 10:05 ET, within a five-minute window.',
      exit: 'Close after 15 minutes, or earlier at a risk limit.',
    }
  return {
    entry: `Price exceeds the previous ${version.breakout_period || 20} bars’ high.${version.family === 'news_breakout' ? ' Requires symbol-linked news published and first seen within one hour.' : ''}`,
    exit: 'Price falls below the previous 10 bars’ low.',
  }
}
