'use client'

import { useAtom } from 'jotai'
import { TrendingUp, TrendingDown, Target, DollarSign, BarChart3, Percent } from 'lucide-react'
import { portfolioMetricsAtom } from '@/lib/atoms'
import { cn, formatCurrency, formatPercent } from '@/lib/utils'

export function PortfolioMetrics() {
  const [metrics] = useAtom(portfolioMetricsAtom)

  const isPositive = metrics.totalProfitLoss >= 0

  const metricCards = [
    {
      label: 'Total Trades',
      value: metrics.totalTrades.toString(),
      icon: BarChart3,
      color: 'text-muted-foreground',
    },
    {
      label: 'Active Trades',
      value: metrics.activeTrades.toString(),
      icon: Target,
      color: 'text-blue-500',
    },
    {
      label: 'Win Rate',
      value: metrics.totalTrades > 0 ? `${metrics.winRate.toFixed(1)}%` : '--',
      icon: Percent,
      color: metrics.winRate >= 50 ? 'text-gain' : 'text-loss',
    },
    {
      label: 'Total Invested',
      value: formatCurrency(metrics.totalInvested),
      icon: DollarSign,
      color: 'text-muted-foreground',
    },
    {
      label: 'Current Value',
      value: formatCurrency(metrics.currentValue),
      icon: TrendingUp,
      color: 'text-muted-foreground',
    },
    {
      label: 'Total P&L',
      value: `${isPositive ? '+' : ''}${formatCurrency(metrics.totalProfitLoss)}`,
      subValue: `(${isPositive ? '+' : ''}${formatPercent(metrics.totalProfitLossPct)})`,
      icon: isPositive ? TrendingUp : TrendingDown,
      color: isPositive ? 'text-gain' : 'text-loss',
    },
  ]

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {metricCards.map(({ label, value, subValue, icon: Icon, color }) => (
        <div
          key={label}
          className="rounded-lg border bg-card p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <Icon className={cn('h-4 w-4', color)} />
            <span className="text-sm text-muted-foreground">{label}</span>
          </div>
          <div className={cn('text-xl font-bold', color)}>
            {value}
          </div>
          {subValue && (
            <div className={cn('text-sm', color)}>
              {subValue}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
