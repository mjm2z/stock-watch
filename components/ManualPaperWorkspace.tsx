'use client'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { PaperWorkspaceTabs } from './PaperWorkspaceTabs'
import { InteractiveChart } from './MarketChart'
import { OperatorAccess } from './SystemsWorkspace'
import capabilities from '@/worker/src/stock_watch_worker/manual/capabilities.json'

type Row = Record<string, any>
type Asset = 'stocks' | 'bitcoin'
const input = 'mt-1 block w-full rounded-md border bg-background px-3 py-2'
const button = 'rounded-md border px-3 py-2 text-sm disabled:opacity-40'
const terminal = ['filled', 'canceled', 'expired', 'rejected']
const requestId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(16)), (v) =>
    v.toString(16).padStart(2, '0')
  ).join('')

export function ManualPaperWorkspace({
  initialAsset = 'stocks',
  embedded = false,
}: {
  initialAsset?: Asset
  embedded?: boolean
}) {
  const router = useRouter()
  const [data, setData] = useState<Row>({})
  const [authorized, setAuthorized] = useState(false)
  const [notice, setNotice] = useState('')
  const [draft, setDraft] = useState<Row | null>(null)
  const [asset, setAsset] = useState<Asset>(initialAsset)
  const [ticket, setTicket] = useState({
    symbol: 'SPY',
    side: 'buy',
    qty: '',
    notional: '50',
    limit: '',
    order_type: 'limit',
    stop_price: '',
    condition: '',
    threshold: '',
    time_in_force: initialAsset === 'stocks' ? 'day' : 'gtc',
  })
  const [busy, setBusy] = useState(false)
  const [clock, setClock] = useState(Date.now())
  const [selected, setSelected] = useState<Row | null>(null)
  const revision = useRef(0)
  useEffect(() => {
    setAsset(initialAsset)
    setDraft(null)
    setTicket((t) => ({
      ...t,
      order_type: 'limit',
      condition: '',
      time_in_force: initialAsset === 'stocks' ? 'day' : 'gtc',
    }))
    revision.current++
  }, [initialAsset])
  async function refresh(signal?: AbortSignal) {
    const response = await fetch('/api/manual-paper', { signal, cache: 'no-store' })
    const result = await response.json()
    if (!response.ok) throw Error(result.error || 'Manual paper service unavailable')
    setData(result)
  }
  useEffect(() => {
    const controller = new AbortController()
    void refresh(controller.signal).catch((e) => {
      if (!controller.signal.aborted) setNotice(e.message)
    })
    const timer = setInterval(() => {
      setClock(Date.now())
      void refresh(controller.signal).catch(() => {})
    }, 5000)
    return () => {
      clearInterval(timer)
      controller.abort()
    }
  }, [])
  function edit(key: keyof typeof ticket, value: string) {
    revision.current++
    setDraft(null)
    setTicket((old) => ({
      ...old,
      [key]: value,
      ...(key === 'order_type'
        ? {
            condition: '',
            ...(asset === 'bitcoin' && value === 'stop_limit' ? { time_in_force: 'gtc' } : {}),
          }
        : {}),
    }))
  }
  async function send(body: Row) {
    if (busy) return
    const issuedRevision = revision.current
    setBusy(true)
    setNotice('')
    try {
      const response = await fetch('/api/manual-paper', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const result = await response.json()
      if (!response.ok) throw Error(result.error || 'Request failed')
      if (body.operation === 'preview') {
        if (issuedRevision === revision.current) setDraft(result)
      } else {
        setDraft(null)
        setNotice('Instruction confirmed. Follow reconciliation below; submission is not a fill.')
        await refresh()
      }
    } catch (e) {
      setNotice(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }
  function preview(command: Row) {
    setDraft(null)
    void send({ operation: 'preview', request_id: requestId(), command })
  }
  const instructions: Row[] = (data.instructions || []).filter((r: Row) => r.asset === asset)
  const plans: Row[] = (data.protective_plans || []).filter((p: Row) =>
    instructions.some((i) => i.id === p.parent)
  )
  const account = (data.accounts || []).find((a: Row) => a.asset === asset)
  const performance = data.balances?.[0]?.allocations?.find((r: Row) => r.asset === asset)
  const history = [...(data.allocation_history || [])]
    .filter((r: Row) => r.asset === asset && r.net_return != null)
    .reverse()
  const balance =
    data.balances?.[0]?.[asset === 'stocks' ? 'allocated_stocks' : 'allocated_bitcoin']
  const marketBuy = ticket.order_type === 'market' && ticket.side === 'buy'
  const hasLimit = ['limit', 'stop_limit'].includes(ticket.order_type)
  const hasStop = ['stop', 'stop_limit'].includes(ticket.order_type)
  const ready = authorized && data.manual === 'configured' && !busy
  const Tag = embedded ? 'section' : 'main'
  return (
    <Tag className={embedded ? 'space-y-5' : 'container mx-auto space-y-5 p-4 sm:p-8'}>
      <PaperWorkspaceTabs asset={asset} active="manual" />
      <header>
        <h1 className="text-2xl font-semibold">Manual paper trading</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Separate $1,000 stock and Bitcoin allocations · $100 entry cap including 1% fee reserve.
          Simulated broker cash is not your spending limit.
        </p>
      </header>
      <div className="flex flex-wrap items-center gap-3">
        <label>
          Allocation
          <select
            className={input}
            value={asset}
            onChange={(e) => {
              const next = e.target.value as Asset
              revision.current++
              setAsset(next)
              if (!embedded)
                router.replace('/manual-paper' + (next === 'bitcoin' ? '?asset=bitcoin' : ''), {
                  scroll: false,
                })
              setDraft(null)
              setTicket((t) => ({
                ...t,
                order_type: 'limit',
                condition: '',
                time_in_force: next === 'stocks' ? 'day' : 'gtc',
              }))
            }}
          >
            <option value="stocks">Manual stocks</option>
            <option value="bitcoin">Manual Bitcoin</option>
          </select>
        </label>
        <p className="text-sm">
          {data.manual || 'Checking service…'} · Budget ${account?.budget || '1,000'} · Unreserved
          cash {balance == null ? 'unavailable' : '$' + balance} · {capabilities[asset].session}
        </p>
        <a
          href={asset === 'stocks' ? '/portfolio' : '/crypto?view=paper'}
          className="ml-auto text-sm underline"
        >
          Automated portfolios
        </a>
      </div>
      <OperatorAccess onChange={setAuthorized} />
      {(notice || data.error) && (
        <p role="status" className="rounded border p-3">
          {notice || data.error}
        </p>
      )}
      {data.manual !== 'configured' && (
        <section className="rounded-xl border bg-card p-4">
          <h2 className="font-semibold">Account setup required</h2>
          <p className="my-2 text-sm">
            Save the dedicated account’s paper credentials in protected server configuration. Setup
            verifies an empty $1,000,000 account distinct from both automated accounts. It never
            resets an account.
          </p>
          <button
            className={button}
            disabled={!authorized || busy}
            onClick={() => preview({ action: 'setup', asset: 'combined' })}
          >
            Preview combined account setup
          </button>
        </section>
      )}
      <form
        className="rounded-xl border bg-card p-5"
        onSubmit={(e) => {
          e.preventDefault()
          preview({
            action: 'order',
            asset,
            symbol: asset === 'bitcoin' ? 'BTC/USD' : ticket.symbol.trim().toUpperCase(),
            side: ticket.side,
            order_type: ticket.order_type,
            time_in_force: ticket.time_in_force,
            ...(marketBuy ? { notional: ticket.notional } : { qty: ticket.qty }),
            ...(hasLimit ? { limit: ticket.limit } : {}),
            ...(hasStop ? { stop_price: ticket.stop_price } : {}),
            ...(ticket.condition
              ? { condition: ticket.condition, threshold: ticket.threshold }
              : {}),
          })
        }}
      >
        <h2 className="mb-4 text-lg font-semibold">Place a paper order</h2>
        <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label>
            Symbol
            <input
              className={input}
              value={asset === 'bitcoin' ? 'BTC/USD' : ticket.symbol}
              readOnly={asset === 'bitcoin'}
              required
              maxLength={15}
              onChange={(e) => edit('symbol', e.target.value)}
            />
          </label>
          <label>
            Side
            <select
              className={input}
              value={ticket.side}
              onChange={(e) => {
                edit('side', e.target.value)
                if (ticket.order_type === 'stop' && e.target.value === 'buy')
                  edit('order_type', 'limit')
              }}
            >
              <option value="buy">Buy</option>
              <option value="sell">Sell owned quantity</option>
            </select>
          </label>
          <label>
            Order type
            <select
              className={input}
              value={ticket.order_type}
              onChange={(e) => edit('order_type', e.target.value)}
            >
              {capabilities[asset].order_types
                .filter((t) => t !== 'stop' || ticket.side === 'sell')
                .map((t) => (
                  <option key={t} value={t}>
                    {
                      (
                        {
                          limit: 'Limit (default)',
                          market: 'Market',
                          stop_limit: 'Stop-limit',
                          stop: 'Stop-market exit',
                        } as Row
                      )[t]
                    }
                  </option>
                ))}
            </select>
          </label>
          <label>
            Time in force
            <select
              className={input}
              value={ticket.time_in_force}
              onChange={(e) => edit('time_in_force', e.target.value)}
            >
              {capabilities[asset].time_in_force
                .filter((t) => !(asset === 'bitcoin' && hasStop && t !== 'gtc'))
                .map((t) => (
                  <option key={t} value={t}>
                    {t.toUpperCase()}
                  </option>
                ))}
            </select>
          </label>
          <label>
            {marketBuy ? 'Dollar amount (before fee reserve)' : 'Quantity'}
            <input
              className={input}
              inputMode="decimal"
              required
              value={marketBuy ? ticket.notional : ticket.qty}
              onChange={(e) => edit(marketBuy ? 'notional' : 'qty', e.target.value)}
            />
          </label>
          {hasLimit && (
            <label>
              Limit price ($)
              <input
                className={input}
                inputMode="decimal"
                required
                value={ticket.limit}
                onChange={(e) => edit('limit', e.target.value)}
              />
            </label>
          )}
          {hasStop && (
            <label>
              Broker stop price ($)
              <input
                className={input}
                inputMode="decimal"
                required
                value={ticket.stop_price}
                onChange={(e) => edit('stop_price', e.target.value)}
              />
            </label>
          )}
          {ticket.order_type === 'limit' && (
            <label>
              Local trigger
              <select
                className={input}
                value={ticket.condition}
                onChange={(e) => edit('condition', e.target.value)}
              >
                <option value="">Submit limit</option>
                <option value="above">At or above</option>
                <option value="below">At or below</option>
              </select>
            </label>
          )}
          {ticket.condition && (
            <label>
              Trigger price ($)
              <input
                required
                className={input}
                inputMode="decimal"
                value={ticket.threshold}
                onChange={(e) => edit('threshold', e.target.value)}
              />
            </label>
          )}
        </fieldset>
        <p className="my-4 text-sm text-muted-foreground">
          {ticket.order_type === 'market'
            ? 'Market orders have no guaranteed price. Buys use a fixed dollar amount; fills determine quantity.'
            : 'Limits may not fill. Stop-limit activation does not guarantee an exit.'}{' '}
          {asset === 'stocks' && 'Fractional stocks must be broker-eligible and use DAY.'}{' '}
          {ticket.condition &&
            'Local triggers require StockWatch online; buy limits must be within 0.5% above the trigger.'}{' '}
          Entry instructions expire locally after 24 hours.
        </p>
        <button className={button} disabled={!ready}>
          {busy ? 'Checking…' : 'Preview order'}
        </button>
      </form>
      {draft && (
        <section
          className="rounded-xl border border-primary bg-card p-5"
          aria-label="Order confirmation"
        >
          <h2 className="font-semibold">Review exact instruction · two-minute confirmation</h2>
          <dl className="my-4 grid gap-3 sm:grid-cols-3">
            {Object.entries(draft.preview)
              .filter(
                ([key, value]) =>
                  value != null &&
                  typeof value !== 'object' &&
                  !['quote', 'observation'].includes(key) &&
                  !(key === 'qty' && draft.preview.notional) &&
                  !(
                    ['limit', 'limit_price'].includes(key) &&
                    ['market', 'stop'].includes(String(draft.preview.order_type))
                  )
              )
              .map(([key, value]) => (
                <div key={key}>
                  <dt className="text-xs capitalize text-muted-foreground">
                    {key.replaceAll('_', ' ')}
                  </dt>
                  <dd className="break-words text-sm tabular-nums">{String(value)}</dd>
                </div>
              ))}
          </dl>
          {draft.preview.already_satisfied && (
            <p className="mb-3 font-semibold">
              The condition is already satisfied and may execute immediately after confirmation.
            </p>
          )}
          <button
            className={button}
            disabled={!authorized || busy || !draft.token || clock >= draft.expires * 1000}
            onClick={() =>
              void send({
                operation: 'confirm',
                id: draft.id,
                revision: draft.revision,
                token: draft.token,
              })
            }
          >
            {clock >= draft.expires * 1000
              ? 'Expired — preview again'
              : 'Confirm paper instruction'}
          </button>
          <button
            className={`${button} ml-2`}
            onClick={() => {
              revision.current++
              setDraft(null)
            }}
          >
            Dismiss
          </button>
        </section>
      )}
      <section className="rounded-xl border p-4">
        <h2 className="text-lg font-semibold">
          {asset === 'stocks' ? 'Stocks' : 'Bitcoin'} allocation performance
        </h2>
        <p className="text-sm">
          $1,000 starting budget · USD · broker-paper observations ·{' '}
          {performance?.status || 'No reconciled valuations yet'}
        </p>
        <dl className="my-3 grid grid-cols-3 gap-3 text-sm">
          <div>
            <dt>Net P&L</dt>
            <dd>{performance?.net_pnl != null ? '$' + performance.net_pnl : 'Unavailable'}</dd>
          </div>
          <div>
            <dt>Net return</dt>
            <dd>
              {performance?.net_return != null
                ? (performance.net_return * 100).toFixed(2) + '%'
                : 'Unavailable'}
            </dd>
          </div>
          <div>
            <dt>Equity</dt>
            <dd>{performance?.equity != null ? '$' + performance.equity : 'Unavailable'}</dd>
          </div>
          <div>
            <dt>Maximum observed drawdown</dt>
            <dd>
              {performance?.maximum_observed_drawdown != null
                ? (performance.maximum_observed_drawdown * 100).toFixed(2) + '%'
                : 'Unavailable'}
            </dd>
          </div>
        </dl>
        {performance?.unavailable_reason && <p>{performance.unavailable_reason}</p>}
        {history.length > 1 && (
          <InteractiveChart
            bars={history.map((r: Row) => ({
              at: new Date(r.as_of * 1000).toISOString(),
              open: r.net_return * 100,
              high: r.net_return * 100,
              low: r.net_return * 100,
              close: r.net_return * 100,
              volume: 0,
            }))}
            percent
            label="Manual allocation net return"
          />
        )}
        <p className="text-xs text-muted-foreground">
          Prospective observations only; missing periods are not reconstructed. Posted fees may
          arrive late. Benchmark unavailable until matching funding, valuations and dividend
          treatment are established.
        </p>
      </section>
      <Records
        title="Attributed manual positions"
        rows={(data.owned_positions || []).filter((r: Row) => r.asset === asset)}
        columns={{ symbol: 'Symbol', qty: 'Attributed quantity', account_id: 'Paper account' }}
        onSelect={(r) => setSelected({ ...r, record_kind: 'position' })}
      />
      <Records
        title="Instructions and open orders"
        rows={instructions.map((r) => {
          let request: Row = {}
          try {
            request = JSON.parse(r.request)
          } catch {}
          return {
            ...r,
            order_type: request.type,
            sizing: request.notional ? `$${request.notional}` : r.qty,
            price: request.limit_price || 'No fixed price',
          }
        })}
        columns={{
          symbol: 'Symbol',
          side: 'Side',
          order_type: 'Type',
          sizing: 'Size',
          price: 'Limit',
          status: 'Status',
          filled_qty: 'Filled',
        }}
        onSelect={setSelected}
      />
      {selected && (
        <section className="rounded border p-4">
          <div className="flex justify-between">
            <h2 className="font-semibold">Instruction evidence</h2>
            <button className={button} onClick={() => setSelected(null)}>
              Close
            </button>
          </div>
          <p className="my-3 break-all text-sm">
            {selected.id} · {selected.asset} · {selected.account_id}
          </p>
          <pre className="max-h-64 overflow-auto text-xs">{JSON.stringify(selected, null, 2)}</pre>
          {selected.record_kind === 'position' && (
            <PositionExit
              key={selected.asset + selected.symbol}
              disabled={!ready}
              onPreview={(limit) =>
                preview({ action: 'exit', asset: selected.asset, symbol: selected.symbol, limit })
              }
            />
          )}
          {selected.record_kind === 'plan' && (
            <button
              className={`${button} mt-3`}
              disabled={!ready}
              onClick={() =>
                preview({
                  action: 'cancel_plan',
                  asset: selected.asset,
                  instruction: selected.parent,
                })
              }
            >
              Preview cancel protective plan
            </button>
          )}
          {selected.record_kind !== 'plan' &&
            selected.request &&
            !terminal.includes(selected.status) && (
              <button
                className={`${button} mt-3`}
                disabled={!ready}
                onClick={() =>
                  preview({ action: 'cancel', asset: selected.asset, instruction: selected.id })
                }
              >
                Preview cancellation
              </button>
            )}
          {selected.side === 'buy' &&
            (Number(selected.filled_qty) > 0 || !terminal.includes(selected.status)) && (
              <ProtectionForm
                disabled={!ready}
                onPreview={(values) =>
                  preview({
                    action: 'protect',
                    asset: selected.asset,
                    instruction: selected.id,
                    ...values,
                  })
                }
              />
            )}
        </section>
      )}
      <Records
        title="Protective exit plans · locally monitored; host required"
        rows={plans}
        columns={{
          parent: 'Entry',
          stop_loss: 'Stop loss',
          take_profit: 'Take profit',
          status: 'Status',
        }}
        onSelect={(p) => setSelected({ ...p, asset, record_kind: 'plan' })}
      />
      <Records
        title="Recent activity"
        rows={(data.activity || [])
          .filter((r: Row) => r.asset === asset)
          .map((r: Row) => ({ ...r, time: new Date(r.at * 1000).toLocaleString() }))}
        columns={{ time: 'Observed at', symbol: 'Symbol', kind: 'Event', status: 'Status' }}
        onSelect={setSelected}
      />
      <details className="rounded border p-4">
        <summary>Broker account reconciliation (combined account, not allocation returns)</summary>
        <Records
          title="Broker account P&L"
          rows={(data.pnl || []).map((r: Row) => ({ ...r, ...r.performance }))}
          columns={{ asset: 'Scope', total_pnl: 'Reconciled P&L', status: 'Accounting status' }}
        />
        <p className="text-sm text-muted-foreground">
          Separate allocation returns require attributable fees and valuations. Unavailable values
          are not zero. Neither allocation is measured against the $1,000,000 broker balance.
        </p>
      </details>
    </Tag>
  )
}
function ProtectionForm({
  disabled,
  onPreview,
}: {
  disabled: boolean
  onPreview: (values: Row) => void
}) {
  const [stop, setStop] = useState('')
  const [take, setTake] = useState('')
  return (
    <form
      className="mt-4 flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        onPreview({ ...(stop ? { stop_loss: stop } : {}), ...(take ? { take_profit: take } : {}) })
      }}
    >
      <label>
        Stop loss
        <input
          className={input}
          value={stop}
          onChange={(e) => setStop(e.target.value)}
          inputMode="decimal"
        />
      </label>
      <label>
        Take profit
        <input
          className={input}
          value={take}
          onChange={(e) => setTake(e.target.value)}
          inputMode="decimal"
        />
      </label>
      <button className={button} disabled={disabled || (!stop && !take)}>
        Preview exit plan
      </button>
      <p className="w-full text-sm text-muted-foreground">
        Protects actual fills. Local exits are not broker-atomic OCO and remain active until the
        position closes or you cancel the plan.
      </p>
    </form>
  )
}
function Records({
  title,
  rows,
  columns,
  onSelect,
}: {
  title: string
  rows: Row[]
  columns: Record<string, string>
  onSelect?: (row: Row) => void
}) {
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      {!rows.length ? (
        <p className="text-sm text-muted-foreground">No records yet.</p>
      ) : (
        <div className="overflow-auto rounded border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                {Object.values(columns).map((label) => (
                  <th className="p-3" key={label}>
                    {label}
                  </th>
                ))}
                {onSelect && <th className="p-3">Details</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr className="border-t" key={row.id || i}>
                  {Object.keys(columns).map((key) => (
                    <td className="max-w-64 break-words p-3 tabular-nums" key={key}>
                      {row[key] == null ? 'Unavailable' : String(row[key])}
                    </td>
                  ))}
                  {onSelect && (
                    <td className="p-3">
                      <button className="underline" onClick={() => onSelect(row)}>
                        Inspect
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function PositionExit({
  disabled,
  onPreview,
}: {
  disabled: boolean
  onPreview: (limit: string) => void
}) {
  const [limit, setLimit] = useState('')
  return (
    <form
      className="mt-3 flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        onPreview(limit)
      }}
    >
      <label>
        Minimum exit price ($)
        <input
          required
          className={input}
          inputMode="decimal"
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
        />
      </label>
      <button className={button} disabled={disabled}>
        Preview full position exit
      </button>
      <p className="w-full text-xs text-muted-foreground">
        Broker ownership and pending reservations are rechecked. Reconcile cancellations or
        conflicting protective plans before replacing exits. Limits may not fill.
      </p>
    </form>
  )
}
