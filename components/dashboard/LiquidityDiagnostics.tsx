import Link from 'next/link'
import { readLiquidityDiagnostics, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'
import { formatCurrency, formatTimestamp } from '@/lib/utils'
export function LiquidityDiagnostics() {
  try {
    const data = readLiquidityDiagnostics()
    if (!data) return null
    return (
      <section className="space-y-4 rounded-xl border bg-card p-5">
        <div>
          <h2 className="text-lg font-semibold">Liquidity & risk diagnostics</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Frozen inputs from {formatTimestamp(data.at)} ET · {data.companies} companies ·{' '}
            {data.strategyId}
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ['High-risk companies', data.highRisk],
            ['Below $20M IEX dollar volume', data.lowVolume],
            ['Liquidity is the only high-risk trigger', data.liquidityOnly],
            ['Only rejection: liquidity-driven risk', data.riskOnlyRejection],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg bg-muted/40 p-3">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
            </div>
          ))}
        </div>
        <p className="text-sm text-muted-foreground">
          Other high-risk triggers: {data.volatility} companies above 60% annualized volatility;{' '}
          {data.drawdown} with a drawdown worse than −30%. Triggers overlap. {data.missingInputs}{' '}
          companies have incomplete risk inputs.
        </p>
        <p className="text-sm text-muted-foreground">
          The current rule flags average daily dollar volume below $20M as high risk and below $50M
          as medium risk. This uses 21 bars of IEX volume, which covers one exchange. These counts
          measure the current rules; they do not establish what would qualify using consolidated
          market data.{' '}
          <a
            href="https://docs.alpaca.markets/us/docs/market-data-faq"
            className="text-primary underline"
            target="_blank"
            rel="noreferrer"
          >
            Alpaca feed documentation
          </a>
        </p>
        {data.examples.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm font-medium text-primary">
              Inspect liquidity-driven rejections
            </summary>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th>Company</th>
                    <th>Rank score</th>
                    <th>Avg daily IEX dollars</th>
                    <th>Volatility</th>
                    <th>Drawdown</th>
                  </tr>
                </thead>
                <tbody>
                  {data.examples.map((row) => (
                    <tr key={row.symbol} className="border-b">
                      <td className="py-2">
                        <Link
                          className="text-primary underline"
                          href={`/signals?symbol=${row.symbol}`}
                        >
                          {row.symbol}
                        </Link>
                      </td>
                      <td>{row.score.toFixed(1)}</td>
                      <td>{row.liquidity === null ? '—' : formatCurrency(row.liquidity)}</td>
                      <td>
                        {row.volatility === null ? '—' : (row.volatility * 100).toFixed(1) + '%'}
                      </td>
                      <td>{row.drawdown === null ? '—' : (row.drawdown * 100).toFixed(1) + '%'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </section>
    )
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable) return null
    throw error
  }
}
