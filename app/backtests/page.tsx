import { DatabaseUnavailable } from '@/components/dashboard/DatabaseUnavailable'
import { StatusBadge } from '@/components/dashboard/StatusBadge'
import { readDashboardBacktests, WorkerDatabaseUnavailable } from '@/lib/worker-dashboard'

export const dynamic = 'force-dynamic'

export default function BacktestsPage() {
  try {
    const backtests = readDashboardBacktests()
    return (
      <main className="container mx-auto space-y-6 p-4 sm:p-8">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Backtest experiments</h1>
          <p className="mt-2 text-muted-foreground">
            Chronological walk-forward results and reproducibility metadata.
          </p>
        </div>
        {backtests.length ? (
          <div className="grid gap-5 lg:grid-cols-2">
            {backtests.map((run) => {
              const summary = metricObject(run.metrics.summary)
              const reliability = metricObject(run.metrics.out_of_sample_reliability)
              const membershipMode = metricText(run.metrics.universe_membership_mode)
              const selectedThresholds = uniqueMetricNumbers(
                metricObject(run.metrics.selected_thresholds)
              )
              const underpoweredSplits = metricNumber(run.metrics.underpowered_validation_splits)
              const portfolio = metricObject(run.metrics.portfolio)
              const portfolioStatus = metricText(portfolio.status)
              const portfolioStock = metricObject(portfolio.stock)
              const portfolioSpy = metricObject(portfolio.spy)
              const portfolioExcess = metricObject(portfolio.excess)
              const portfolioExposure = metricObject(portfolio.exposure)
              const portfolioTurnover = metricObject(portfolio.turnover)
              const overallReliability = metricObject(reliability.overall)
              const reliabilityStatus = metricText(overallReliability.status)
              const cohortRows = [
                ...reliabilityRows(
                  metricObject(reliability.by_horizon),
                  (value) => `${value}-session`
                ),
                ...reliabilityRows(
                  metricObject(reliability.by_score_bucket),
                  (value) => `Score ${value}`
                ),
              ]
              return (
                <article key={run.id} className="rounded-xl border bg-card p-5 shadow-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="font-semibold">{run.strategyName}</h2>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">{run.id}</p>
                    </div>
                    <StatusBadge status={run.status} />
                  </div>
                  <dl className="mt-5 grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <dt className="text-xs text-muted-foreground">Trades</dt>
                      <dd className="mt-1 font-semibold">{run.tradeCount}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Rejected</dt>
                      <dd className="mt-1 font-semibold">{run.rejectionCount}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Walk-forward splits</dt>
                      <dd className="mt-1 font-semibold">{run.splitCount}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Dataset</dt>
                      <dd className="mt-1">{run.datasetVersion}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Feature set</dt>
                      <dd className="mt-1">{run.featureSetVersion}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Modeled cost</dt>
                      <dd className="mt-1">{run.costBps.toFixed(1)} bps</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Universe membership</dt>
                      <dd className="mt-1">
                        {formatUniverseMembership(membershipMode, run.survivorshipBiased)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Selected threshold(s)</dt>
                      <dd className="mt-1">
                        {selectedThresholds.length ? selectedThresholds.join(', ') : '—'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Validation power</dt>
                      <dd className="mt-1">
                        {underpoweredSplits === null
                          ? '—'
                          : `${underpoweredSplits}/${run.splitCount} splits underpowered`}
                      </dd>
                    </div>
                  </dl>
                  <dl className="mt-5 grid grid-cols-3 gap-3 rounded-lg bg-muted/50 p-3 text-sm">
                    <div>
                      <dt className="text-xs text-muted-foreground">Positive</dt>
                      <dd className="mt-1 font-semibold">
                        {formatRate(metricNumber(summary.positive_rate))}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Beat SPY</dt>
                      <dd className="mt-1 font-semibold">
                        {formatRate(metricNumber(summary.beat_spy_rate))}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Avg excess</dt>
                      <dd className="mt-1 font-semibold">
                        {formatRate(metricNumber(summary.average_excess_return))}
                      </dd>
                    </div>
                  </dl>
                  {portfolioStatus === 'complete' ? (
                    <section className="mt-5 rounded-lg border p-4">
                      <div>
                        <h3 className="text-sm font-semibold">Unlimited-funding portfolio</h3>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Independently funded $5–$15 lots, capped at $30 concurrently per ticker,
                          compared with equal-dollar SPY cohorts on identical dates.
                        </p>
                      </div>
                      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                        <PortfolioMetric
                          label="Contributed"
                          value={formatMoney(metricNumber(portfolioStock.contributed_usd))}
                        />
                        <PortfolioMetric
                          label="Strategy return"
                          value={formatRate(
                            metricNumber(portfolioStock.return_on_contributed_capital)
                          )}
                        />
                        <PortfolioMetric
                          label="Matched SPY return"
                          value={formatRate(
                            metricNumber(portfolioSpy.return_on_contributed_capital)
                          )}
                        />
                        <PortfolioMetric
                          label="Excess P&L"
                          value={formatMoney(metricNumber(portfolioExcess.pnl_usd))}
                        />
                        <PortfolioMetric
                          label="Strategy annualized"
                          value={formatRate(metricNumber(portfolioStock.annualized_return))}
                        />
                        <PortfolioMetric
                          label="SPY annualized"
                          value={formatRate(metricNumber(portfolioSpy.annualized_return))}
                        />
                      </dl>
                      <div className="mt-4 overflow-x-auto">
                        <table className="w-full text-left text-xs">
                          <thead className="text-muted-foreground">
                            <tr>
                              <th className="pb-2 pr-3 font-medium">Risk metric</th>
                              <th className="pb-2 pr-3 font-medium">Strategy</th>
                              <th className="pb-2 font-medium">Matched SPY</th>
                            </tr>
                          </thead>
                          <tbody>
                            <PortfolioComparisonRow
                              label="Maximum drawdown"
                              stock={formatRate(metricNumber(portfolioStock.maximum_drawdown))}
                              spy={formatRate(metricNumber(portfolioSpy.maximum_drawdown))}
                            />
                            <PortfolioComparisonRow
                              label="Annualized volatility"
                              stock={formatRate(metricNumber(portfolioStock.annualized_volatility))}
                              spy={formatRate(metricNumber(portfolioSpy.annualized_volatility))}
                            />
                            <PortfolioComparisonRow
                              label="Sharpe (0% risk-free)"
                              stock={formatDecimal(metricNumber(portfolioStock.sharpe_ratio))}
                              spy={formatDecimal(metricNumber(portfolioSpy.sharpe_ratio))}
                            />
                            <PortfolioComparisonRow
                              label="Sortino (0% target)"
                              stock={formatDecimal(metricNumber(portfolioStock.sortino_ratio))}
                              spy={formatDecimal(metricNumber(portfolioSpy.sortino_ratio))}
                            />
                          </tbody>
                        </table>
                      </div>
                      <dl className="mt-4 grid grid-cols-2 gap-3 border-t pt-4 text-sm sm:grid-cols-4">
                        <PortfolioMetric
                          label="Avg active capital"
                          value={formatMoney(
                            metricNumber(portfolioExposure.average_active_capital_usd)
                          )}
                        />
                        <PortfolioMetric
                          label="Peak active capital"
                          value={formatMoney(
                            metricNumber(portfolioExposure.peak_active_capital_usd)
                          )}
                        />
                        <PortfolioMetric
                          label="Peak concurrent lots"
                          value={formatCount(metricNumber(portfolioExposure.peak_concurrent_lots))}
                        />
                        <PortfolioMetric
                          label="Gross turnover / avg capital"
                          value={formatMultiple(
                            metricNumber(portfolioTurnover.gross_turnover_to_average_active_capital)
                          )}
                        />
                      </dl>
                    </section>
                  ) : null}
                  {Object.keys(overallReliability).length ? (
                    <section className="mt-5 rounded-lg border p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <h3 className="text-sm font-semibold">Out-of-sample reliability</h3>
                          <p className="mt-1 text-xs text-muted-foreground">
                            Empirical test-fold rates with 95% Wilson intervals—not per-signal
                            forecasts.
                          </p>
                        </div>
                        {reliabilityStatus ? <StatusBadge status={reliabilityStatus} /> : null}
                      </div>
                      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                        <ReliabilityMetric
                          label="Positive return"
                          value={metricObject(overallReliability.positive_return)}
                        />
                        <ReliabilityMetric
                          label="Beat SPY"
                          value={metricObject(overallReliability.beat_spy)}
                        />
                      </dl>
                      <p className="mt-3 text-xs text-muted-foreground">
                        n={metricNumber(overallReliability.observations) ?? 0}; minimum for
                        reportable status=
                        {metricNumber(overallReliability.minimum_observations) ?? '—'}.
                      </p>
                      {cohortRows.length ? (
                        <div className="mt-4 overflow-x-auto">
                          <table className="w-full text-left text-xs">
                            <thead className="text-muted-foreground">
                              <tr>
                                <th className="pb-2 pr-3 font-medium">Cohort</th>
                                <th className="pb-2 pr-3 font-medium">n</th>
                                <th className="pb-2 pr-3 font-medium">Positive (95% CI)</th>
                                <th className="pb-2 font-medium">Beat SPY (95% CI)</th>
                              </tr>
                            </thead>
                            <tbody>
                              {cohortRows.map((row) => (
                                <tr key={row.label} className="border-t">
                                  <td className="py-2 pr-3">{row.label}</td>
                                  <td className="py-2 pr-3">{row.observations}</td>
                                  <td className="py-2 pr-3">{formatReliability(row.positive)}</td>
                                  <td className="py-2">{formatReliability(row.beatSpy)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : null}
                    </section>
                  ) : null}
                  <p
                    className="mt-4 truncate font-mono text-[11px] text-muted-foreground"
                    title={run.datasetSha256}
                  >
                    Dataset SHA-256: {run.datasetSha256}
                  </p>
                  {Object.keys(run.metrics).length ? (
                    <details className="mt-5 rounded-lg bg-muted p-3 text-xs">
                      <summary className="cursor-pointer font-medium">Raw audit metrics</summary>
                      <pre className="mt-3 max-h-64 overflow-auto">
                        {JSON.stringify(run.metrics, null, 2)}
                      </pre>
                    </details>
                  ) : null}
                </article>
              )
            })}
          </div>
        ) : (
          <div className="rounded-xl border bg-card p-8 text-center text-sm text-muted-foreground">
            No persisted backtest runs yet.
          </div>
        )}
      </main>
    )
  } catch (error) {
    if (error instanceof WorkerDatabaseUnavailable)
      return (
        <main className="container mx-auto p-4 sm:p-8">
          <DatabaseUnavailable reason={error.message} />
        </main>
      )
    throw error
  }
}

function ReliabilityMetric({ label, value }: { label: string; value: Record<string, unknown> }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-semibold">{formatReliability(value)}</dd>
    </div>
  )
}

function PortfolioMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-semibold">{value}</dd>
    </div>
  )
}

function PortfolioComparisonRow({
  label,
  stock,
  spy,
}: {
  label: string
  stock: string
  spy: string
}) {
  return (
    <tr className="border-t">
      <td className="py-2 pr-3">{label}</td>
      <td className="py-2 pr-3 font-medium">{stock}</td>
      <td className="py-2 font-medium">{spy}</td>
    </tr>
  )
}

function metricObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function metricNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function metricText(value: unknown): string | null {
  return typeof value === 'string' && value.length ? value : null
}

function uniqueMetricNumbers(values: Record<string, unknown>): number[] {
  return Array.from(
    new Set(
      Object.values(values).flatMap((value) => {
        const parsed = metricNumber(value)
        return parsed === null ? [] : [parsed]
      })
    )
  ).sort((left, right) => left - right)
}

function reliabilityRows(
  cohorts: Record<string, unknown>,
  label: (value: string) => string
): Array<{
  label: string
  observations: number
  positive: Record<string, unknown>
  beatSpy: Record<string, unknown>
}> {
  return Object.entries(cohorts).flatMap(([key, raw]) => {
    const cohort = metricObject(raw)
    const observations = metricNumber(cohort.observations) ?? 0
    return observations > 0
      ? [
          {
            label: label(key),
            observations,
            positive: metricObject(cohort.positive_return),
            beatSpy: metricObject(cohort.beat_spy),
          },
        ]
      : []
  })
}

function formatReliability(value: Record<string, unknown>): string {
  const estimate = metricNumber(value.estimate)
  const lower = metricNumber(value.lower_95)
  const upper = metricNumber(value.upper_95)
  if (estimate === null || lower === null || upper === null) return '—'
  return `${formatRate(estimate)} (${formatRate(lower)}–${formatRate(upper)})`
}

function formatUniverseMembership(mode: string | null, biased: boolean): string {
  if (mode === 'point_in_time') return biased ? 'Point-in-time; biased input' : 'Point-in-time'
  return biased ? 'Fixed current snapshot; biased' : 'Fixed snapshot'
}

function formatRate(value: number | null): string {
  return value === null
    ? '—'
    : new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 }).format(value)
}

function formatMoney(value: number | null): string {
  return value === null
    ? '—'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(value)
}

function formatDecimal(value: number | null): string {
  return value === null ? '—' : value.toFixed(2)
}

function formatMultiple(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(2)}×`
}

function formatCount(value: number | null): string {
  return value === null ? '—' : new Intl.NumberFormat('en-US').format(value)
}
