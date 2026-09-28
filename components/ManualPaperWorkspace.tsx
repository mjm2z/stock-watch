'use client'
import { useEffect, useState } from 'react'
import { OperatorAccess } from './SystemsWorkspace'
type RecordValue = Record<string, any>
export function ManualPaperWorkspace() {
  const [data, setData] = useState<RecordValue>({})
  const [authorized, setAuthorized] = useState(false)
  const [notice, setNotice] = useState('')
  const [draft, setDraft] = useState<RecordValue | null>(null)
  const [asset, setAsset] = useState('stocks')
  const [symbol, setSymbol] = useState('')
  const [side, setSide] = useState('buy')
  const [qty, setQty] = useState('')
  const [limit, setLimit] = useState('')
  async function refresh() {
    const response = await fetch('/api/manual-paper')
    setData(await response.json())
  }
  useEffect(() => {
    void refresh().catch(() => setNotice('Manual paper service unavailable.'))
  }, [])
  async function send(body: RecordValue) {
    try {
      const response = await fetch('/api/manual-paper', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const result = await response.json()
      if (!response.ok) throw Error(result.error)
      if (body.operation === 'preview') setDraft(result)
      else {
        setDraft(null)
        setNotice('Confirmed. Follow order status below; submission does not guarantee a fill.')
        await refresh()
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Request failed')
    }
  }
  return (
    <main className="container mx-auto space-y-5 p-6">
      <h1 className="text-3xl font-semibold">Manual paper trading</h1>
      <p>
        One dedicated paper account · separate $1,000 stock and Bitcoin budgets · $100 entry cap
        including fee reserve.
      </p>
      <p>Account status: {data.manual || 'Checking'}. System allocations remain separate.</p>
      <OperatorAccess onChange={setAuthorized} />
      {(data.error || notice) && <p role="status">{notice || data.error}</p>}
      <form
        className="flex flex-wrap gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          void send({
            operation: 'preview',
            request_id: Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
              value.toString(16).padStart(2, '0')
            ).join(''),
            command: {
              action: 'order',
              asset,
              symbol: asset === 'bitcoin' ? 'BTC/USD' : symbol,
              side,
              qty,
              limit,
            },
          })
        }}
      >
        <label>
          Account{' '}
          <select
            value={asset}
            onChange={(e) => {
              setAsset(e.target.value)
              setDraft(null)
            }}
          >
            <option value="stocks">Manual stocks</option>
            <option value="bitcoin">Manual Bitcoin</option>
          </select>
        </label>
        <label>
          Side{' '}
          <select
            value={side}
            onChange={(e) => {
              setSide(e.target.value)
              setDraft(null)
            }}
          >
            <option>buy</option>
            <option>sell</option>
          </select>
        </label>
        {asset === 'stocks' && (
          <label>
            Symbol{' '}
            <input
              required
              className="w-24 border"
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value)
                setDraft(null)
              }}
            />
          </label>
        )}
        <label>
          Quantity{' '}
          <input
            required
            className="w-24 border"
            value={qty}
            onChange={(e) => {
              setQty(e.target.value)
              setDraft(null)
            }}
          />
        </label>
        <label>
          Limit price{' '}
          <input
            required
            className="w-28 border"
            value={limit}
            onChange={(e) => {
              setLimit(e.target.value)
              setDraft(null)
            }}
          />
        </label>
        <button
          className="rounded border px-3 py-2"
          disabled={!authorized || data.manual !== 'configured'}
        >
          Preview order
        </button>
      </form>
      <button
        disabled={!authorized}
        className="rounded border px-3 py-2"
        onClick={() =>
          void send({
            operation: 'preview',
            request_id: Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
              value.toString(16).padStart(2, '0')
            ).join(''),
            command: { action: 'setup', asset: 'combined' },
          })
        }
      >
        Preview combined account setup
      </button>
      {draft && (
        <section className="rounded border p-4">
          <h2>Confirm exact preview · expires in two minutes</h2>
          <dl className="my-3 grid grid-cols-2 gap-2 text-sm">
            {Object.entries({
              Account: draft.preview.asset,
              Action: draft.preview.action,
              Symbol: draft.preview.symbol,
              Side: draft.preview.side,
              Quantity: draft.preview.qty,
              'Limit price': draft.preview.limit,
              'Stocks budget': draft.preview.budgets?.stocks,
              'Bitcoin budget': draft.preview.budgets?.bitcoin,
              'Alpaca paper cash': draft.preview.broker_cash,
              'Entry cap': draft.preview.entry_cap,
              'Fee reserve': draft.preview.fee_allowance,
            })
              .filter(([, v]) => v != null)
              .map(([key, value]) => (
                <div key={key}>
                  <dt className="text-muted-foreground">{key}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
          </dl>
          <button
            className="rounded border p-3"
            disabled={!authorized}
            onClick={() =>
              void send({
                operation: 'confirm',
                id: draft.id,
                revision: draft.revision,
                token: draft.token,
              })
            }
          >
            Confirm paper instruction
          </button>
        </section>
      )}
      <p>
        Broker-held limits can work while StockWatch is offline. Conditional instructions require
        StockWatch online. Limits may never fill.
      </p>
      <button
        className="rounded border px-3 py-2"
        onClick={() => void refresh().catch(() => setNotice('Refresh unavailable'))}
      >
        Refresh activity
      </button>
      <Records
        title="Accounts"
        rows={data.balances || data.accounts || []}
        columns={{ asset: 'Account', account_id: 'Alpaca account', allocated_stocks: 'Stocks available', allocated_bitcoin: 'Bitcoin available', cash: 'Alpaca cash', equity: 'Alpaca equity' }}
      />
      <Records
        title="Drafts"
        rows={(data.drafts || []).map((row: RecordValue) => ({ ...row, ...row.preview }))}
        columns={{ asset: 'Account', action: 'Action', symbol: 'Symbol', state: 'Status' }}
      />
      <Records
        title="Instructions and orders"
        rows={(data.instructions || []).map((row: RecordValue) => {
          let user = ''
          try {
            user = JSON.parse(row.audit).user || 'Protective plan'
          } catch {}
          return { ...row, user }
        })}
        columns={{
          asset: 'Account',
          symbol: 'Symbol',
          side: 'Side',
          qty: 'Quantity',
          limit_price: 'Limit',
          status: 'Status',
          filled_qty: 'Filled',
          user: 'Requested by',
        }}
      />
      <Records
        title="Fill observations"
        rows={data.fills || []}
        columns={{
          instruction_id: 'Instruction',
          cumulative_qty: 'Total filled quantity',
          cumulative_notional: 'Total filled value',
        }}
      />
      <Records
        title="Protective plans"
        rows={data.protective_plans || []}
        columns={{
          parent: 'Entry instruction',
          stop_loss: 'Stop loss',
          take_profit: 'Take profit',
          status: 'Status',
        }}
      />
      <Records
        title="Account P&L"
        rows={(data.pnl || []).map((row: RecordValue) => ({ ...row, ...row.performance }))}
        columns={{
          asset: 'Account',
          broker_unrealized_pl: 'Unrealized P&L',
          total_pnl: 'Reconciled total P&L',
          status: 'Accounting status',
        }}
      />
    </main>
  )
}

function Records({
  title,
  rows,
  columns,
}: {
  title: string
  rows: RecordValue[]
  columns: Record<string, string>
}) {
  return (
    <section>
      <h2 className="text-xl font-semibold">{title}</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No records yet.</p>
      ) : (
        <div className="overflow-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                {Object.entries(columns).map(([key, label]) => (
                  <th className="p-2" key={key}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr className="border-t" key={row.id || index}>
                  {Object.keys(columns).map((key) => (
                    <td className="max-w-64 break-words p-2 tabular-nums" key={key}>
                      {row[key] == null ? 'Unavailable' : String(row[key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
