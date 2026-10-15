'use client'
import { useState } from 'react'
import { ArrowUpRight, Check, Download } from 'lucide-react'
import { CompactDisclosure, PagedRows, StatusBadge } from './CompactDisclosure'
import { cn } from '@/lib/utils'
import {
  date,
  family,
  human,
  parsed,
  percent,
  stateLabel,
  when,
  type Command,
  type ExperimentData,
} from './presentation'

const sourceName = (value: string) =>
  value.startsWith('BLS')
    ? 'BLS'
    : value === 'Federal Reserve'
      ? 'Federal Reserve'
      : value.startsWith('SEC')
        ? 'SEC'
        : value
function ResearchBrief({ items }: { items: ExperimentData['context'] }) {
  const [source, setSource] = useState('All')
  const unique = items.filter(
    (item, index) => items.findIndex((other) => other.url === item.url) === index
  )
  const sources = ['All', ...Array.from(new Set(unique.map((item) => sourceName(item.source))))]
  const filtered =
    source === 'All' ? unique : unique.filter((item) => sourceName(item.source) === source)
  return (
    <>
      <div className="mb-3 flex flex-wrap gap-1.5" aria-label="Research sources">
        {sources.map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={source === name}
            onClick={() => setSource(name)}
            className={cn(
              'rounded-full border px-3 py-1.5 text-[11px] transition-colors',
              source === name
                ? 'border-primary/25 bg-primary/10 text-primary'
                : 'border-border text-muted-foreground hover:bg-muted'
            )}
          >
            {name}
          </button>
        ))}
      </div>
      <PagedRows
        key={source}
        items={filtered}
        label="Research brief"
        render={(item) => (
          <article key={item.id} className="py-3 first:pt-1">
            <div className="mb-1.5 flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted-foreground">
              <span>{sourceName(item.source)}</span>
              {item.symbol && <span className="font-medium text-foreground">{item.symbol}</span>}
              <span className="ml-auto shrink-0 normal-case tracking-normal">
                {date(item.published)}
              </span>
            </div>
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="group flex items-start gap-3 text-sm leading-relaxed hover:text-primary"
            >
              <span className="line-clamp-2 flex-1">{item.title}</span>
              <ArrowUpRight
                size={15}
                className="mt-1 shrink-0 text-muted-foreground group-hover:text-primary"
                aria-hidden="true"
              />
            </a>
          </article>
        )}
      />
      {!filtered.length && (
        <p className="py-3 text-xs text-muted-foreground">No research updates yet.</p>
      )}
      <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
        Source material for your review. These releases do not place trades.
      </p>
    </>
  )
}

function Proposals({
  items,
  disabled,
  active,
  command,
}: {
  items: ExperimentData['proposals']
  disabled: boolean
  active: boolean
  command: Command
}) {
  const latest = items.reduce((week, item) => (item.week > week ? item.week : week), '')
  const proposals = items.filter((item) => item.week === latest)
  const groups = Array.from(new Set(proposals.map((item) => item.family)))
  const labels: Record<string, string> = {
    trend_fast: 'Fast EMA',
    breakout_period: 'Breakout bars',
    rsi_entry: 'RSI entry',
    news_minutes: 'News window',
  }
  return (
    <>
      <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
        One rule change per idea. Review a new batch before any change can trade.
        {active ? ' Finish the current batch before preparing another.' : ''}
      </p>
      <PagedRows
        items={groups}
        label="Strategy ideas"
        pageSize={2}
        render={(name) => (
          <div key={name} className="py-3 first:pt-0">
            <h3 className="mb-2 text-sm font-medium">{family(name).title}</h3>
            <div className="space-y-2">
              {proposals
                .filter((item) => item.family === name)
                .slice(0, 2)
                .map((item) => {
                  const evidence = parsed<{
                    changes?: Record<string, { before: number; after: number }>
                  }>(item.evidence_json, {})
                  const change = Object.entries(evidence.changes || {})
                    .map(
                      ([key, value]) =>
                        `${labels[key] || human(key)}: ${value.before} → ${value.after}`
                    )
                    .join(' · ')
                  return (
                    <div
                      key={item.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/20 px-3 py-2"
                    >
                      <p className="text-xs text-muted-foreground">
                        {change || `Variant ${item.variant}`}
                      </p>
                      <button
                        className="rounded px-1 py-1 text-xs font-medium text-primary disabled:opacity-40"
                        disabled={disabled || active}
                        onClick={() => void command('preview', { proposal_id: item.id })}
                      >
                        Review idea
                        <span className="sr-only">
                          : {family(name).title}, variant {item.variant}
                        </span>
                      </button>
                    </div>
                  )
                })}
            </div>
          </div>
        )}
      />
      {!items.length && <p className="text-xs text-muted-foreground">No new ideas this week.</p>}
    </>
  )
}

const actionName: Record<string, string> = {
  preview: 'Prepare batch',
  approve: 'Approve batch',
  pause: 'Pause entries',
  resume: 'Resume entries',
  exit: 'Exit positions',
  exit_and_pause: 'Exit and pause',
}
function RecentActivity({ data }: { data: ExperimentData }) {
  return (
    <div className="space-y-4">
      {data.commands.length > 0 && (
        <PagedRows
          items={data.commands}
          pageSize={4}
          label="Recent requests"
          render={(item) => {
            const result = parsed<{ error?: string }>(item.result_json, {})
            return (
              <div key={item.id} className="py-2.5 first:pt-0">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-medium">
                    {actionName[item.action] || human(item.action)}
                  </p>
                  <StatusBadge
                    tone={
                      item.status === 'failed'
                        ? 'attention'
                        : item.status === 'succeeded'
                          ? 'good'
                          : 'neutral'
                    }
                  >
                    {stateLabel(item.status)}
                  </StatusBadge>
                </div>
                {result.error ? (
                  <p className="mt-1.5 text-xs leading-relaxed text-loss">{result.error}</p>
                ) : (
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {item.created ? when(item.created) : 'Paper trading request'}
                  </p>
                )}
              </div>
            )
          }}
        />
      )}
      {!data.commands.length && !data.research.length && (
        <p className="text-xs text-muted-foreground">
          Requests and replay results will appear here.
        </p>
      )}
      {data.research.length > 0 && (
        <div className="border-t border-border pt-4">
          <PagedRows
            items={data.research}
            pageSize={2}
            label="Replay results"
            render={(item) => {
              const result = parsed<{
                start?: string
                end?: string
                ticks?: number
                metrics?: { family: string; allocated_return: number; fills: number }[]
              }>(item.result_json, {})
              return (
                <div key={item.id} className="py-2 first:pt-0">
                  <CompactDisclosure
                    compact
                    title="Paper replay"
                    summary={`${date(result.start || item.created_at)}${result.end ? ' – ' + date(result.end) : ''}`}
                    badge={
                      <StatusBadge tone={item.status === 'failed' ? 'attention' : 'neutral'}>
                        {stateLabel(item.status)}
                      </StatusBadge>
                    }
                  >
                    {item.error && <p className="text-xs text-loss">{item.error}</p>}
                    {item.status === 'succeeded' && (
                      <>
                        <div className="space-y-2">
                          {result.metrics?.slice(0, 5).map((metric) => (
                            <div
                              key={metric.family}
                              className="flex items-center justify-between gap-3 text-xs"
                            >
                              <span className="text-muted-foreground">
                                {family(metric.family).title}
                              </span>
                              <span className="tabular-nums">
                                {percent(metric.allocated_return)}{' '}
                                <span className="ml-2 text-muted-foreground">
                                  {metric.fills} fills
                                </span>
                              </span>
                            </div>
                          ))}
                        </div>
                        <p className="mt-3 text-[11px] text-muted-foreground">
                          Simulated fills from captured data. Results do not qualify a strategy for
                          trading.
                        </p>
                        <div className="mt-3 flex flex-wrap gap-3">
                          {['summary', 'evidence', 'replay'].map((kind) => (
                            <a
                              key={kind}
                              className="inline-flex items-center gap-1 text-xs text-primary"
                              href={`/api/systems/experiments/artifact?job=${item.id}&kind=${kind}`}
                            >
                              <Download size={12} aria-hidden="true" />
                              {kind === 'summary' ? 'Full report' : human(kind)}
                            </a>
                          ))}
                        </div>
                      </>
                    )}
                  </CompactDisclosure>
                </div>
              )
            }}
          />
        </div>
      )}
    </div>
  )
}

const healthNames: Record<string, string> = {
  'collection:stocks': 'Stock price history',
  'collection:bitcoin': 'Bitcoin price history',
  'stream:stocks': 'Stock price feed',
  'stream:bitcoin': 'Bitcoin price feed',
  'stock-baseline-owner': 'Existing stock strategies',
  'stock-experiment-owner': 'Stock experiment service',
  'bitcoin-experiment-owner': 'Bitcoin experiment service',
  'preflight:stocks': 'Stock approval checks',
  'preflight:bitcoin': 'Bitcoin approval checks',
  'settlement-calendar': 'Settlement calendar',
  'execution:stocks': 'Stock execution',
  'execution:bitcoin': 'Bitcoin execution',
  news: 'News feed',
  storage: 'Evidence storage',
}
export function ResearchPanels({
  data,
  disabled,
  active,
  command,
}: {
  data: ExperimentData
  disabled: boolean
  active: boolean
  command: Command
}) {
  const issues = data.health.filter((item) => item.error)
  return (
    <div className="grid min-w-0 items-start gap-3 lg:grid-cols-2">
      <CompactDisclosure
        title="Research brief"
        summary="The latest filings and economic releases."
        badge={<StatusBadge>{data.context.length} updates</StatusBadge>}
      >
        <ResearchBrief items={data.context} />
      </CompactDisclosure>
      <CompactDisclosure
        title="Strategy ideas"
        summary="Small rule changes for a future batch."
        badge={
          <StatusBadge>
            {new Set(data.proposals.map((item) => item.family)).size} strategies
          </StatusBadge>
        }
      >
        <Proposals items={data.proposals} disabled={disabled} active={active} command={command} />
      </CompactDisclosure>
      <CompactDisclosure
        title="Recent activity"
        summary="Requests, approvals and replay results."
        badge={<StatusBadge>{data.commands.length + data.research.length}</StatusBadge>}
      >
        <RecentActivity data={data} />
      </CompactDisclosure>
      <CompactDisclosure
        title="System status"
        summary={
          issues.length
            ? `${issues.length} items need attention.`
            : 'Data collection and execution services.'
        }
        badge={
          <StatusBadge tone={issues.length ? 'attention' : 'neutral'}>
            {issues.length ? 'Review' : `${data.health.length} reporting`}
          </StatusBadge>
        }
      >
        <PagedRows
          items={[...issues, ...data.health.filter((item) => !item.error)]}
          pageSize={4}
          label="System status"
          render={(item) => (
            <div key={item.component} className="py-2.5 first:pt-0">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span>
                  {healthNames[item.component] || human(item.component.replace('context:', ''))}
                </span>
                {!item.error && (
                  <Check
                    className="shrink-0 text-primary"
                    size={14}
                    aria-label="No reported error"
                  />
                )}
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                {item.error || `Updated ${when(item.at)}`}
              </p>
            </div>
          )}
        />
        {!data.health.length && (
          <p className="text-xs text-muted-foreground">Waiting for the first service update.</p>
        )}
      </CompactDisclosure>
    </div>
  )
}
