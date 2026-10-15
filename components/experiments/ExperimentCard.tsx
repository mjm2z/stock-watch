'use client'
import { useState } from 'react'
import { Activity, Clock3, Newspaper, Pause, Play, TrendingUp, Waves } from 'lucide-react'
import { cn } from '@/lib/utils'
import { CompactDisclosure, StatusBadge } from './CompactDisclosure'
import { ExperimentActivity } from './ExperimentActivity'
import {
  amount,
  duration,
  family,
  percent,
  reason,
  rules,
  stateLabel,
  when,
  type Asset,
  type Command,
  type Instance,
  type Version,
} from './presentation'

const icons = {
  trend: TrendingUp,
  breakout: Activity,
  reversal: Waves,
  news_breakout: Newspaper,
  control: Clock3,
}
export function ExperimentCard({
  name,
  version,
  instance,
  asset,
  disabled,
  preview = false,
  archived = false,
  riskBlocked = false,
  command,
}: {
  name: string
  version?: Version
  instance?: Instance
  asset: Asset
  disabled: boolean
  preview?: boolean
  archived?: boolean
  riskBlocked?: boolean
  command: Command
}) {
  const [activity, setActivity] = useState(false)
  const info = family(name),
    Icon = icons[name as keyof typeof icons] || Activity
  const paused = Boolean(instance?.paused || instance?.state === 'paused')
  const state = archived
    ? 'Completed'
    : instance
      ? stateLabel(instance.state)
      : preview
        ? 'Awaiting approval'
        : 'Planned'
  const budget = instance?.budget || version?.allocation || (name === 'control' ? '50' : '200')
  const rule = version && rules(version)
  return (
    <article
      aria-label={info.title}
      className={cn(
        'flex min-w-0 flex-col rounded-xl border bg-card shadow-sm',
        activity ? 'border-primary/40' : 'border-border'
      )}
    >
      <div className="flex items-start justify-between gap-3 px-5 pt-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-primary/10 bg-primary/5 text-primary">
          <Icon size={18} strokeWidth={1.6} aria-hidden="true" />
        </span>
        <StatusBadge
          tone={
            instance?.state === 'blocked'
              ? 'attention'
              : preview || (instance && !paused && !archived)
                ? 'good'
                : 'neutral'
          }
        >
          {state}
        </StatusBadge>
      </div>
      <div className="flex-1 px-5 pb-4 pt-4">
        <h3 className="text-base font-semibold tracking-tight">{info.title}</h3>
        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{info.description}</p>
        <div className="mt-5 flex items-end justify-between gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Allocation</p>
            <p className="mt-1 text-2xl font-medium tracking-tight tabular-nums">
              {amount(budget)}
            </p>
          </div>
          {version && (
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Max hold</p>
              <p className="mt-1 text-sm font-medium">{duration(version.holding_minutes)}</p>
            </div>
          )}
        </div>
        {version && (
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
            <span>
              Stop <strong className="font-medium text-foreground">{percent(version.stop)}</strong>
            </span>
            <span>
              Take profit{' '}
              <strong className="font-medium text-foreground">{percent(version.take)}</strong>
            </span>
          </div>
        )}
        {instance && (
          <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted-foreground">
            {reason(instance.reason)}
          </p>
        )}
      </div>
      {rule && (
        <div className="px-5 pb-4">
          <CompactDisclosure title="Trading rules" compact>
            <dl className="space-y-3 text-xs leading-relaxed">
              <div>
                <dt className="mb-1 font-medium">Entry</dt>
                <dd className="text-muted-foreground">{rule.entry}</dd>
              </div>
              <div>
                <dt className="mb-1 font-medium">Exit</dt>
                <dd className="text-muted-foreground">{rule.exit}</dd>
              </div>
            </dl>
            <p className="mt-3 border-t border-border pt-3 text-[11px] text-muted-foreground">
              {version!.universe.join(' · ')}
            </p>
          </CompactDisclosure>
        </div>
      )}
      {instance && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            className="rounded py-1.5 text-xs font-medium text-primary"
            aria-expanded={activity}
            onClick={() => setActivity(!activity)}
          >
            {activity ? 'Hide activity' : 'View activity'}
          </button>
          {!archived && (
            <button
              className="sw-button !min-h-8 !px-3 !py-1.5 !text-xs"
              disabled={disabled || (paused && riskBlocked)}
              onClick={() =>
                void command(paused ? 'resume' : 'pause', { instance_id: instance.id })
              }
            >
              {paused ? (
                <Play size={12} aria-hidden="true" />
              ) : (
                <Pause size={12} aria-hidden="true" />
              )}
              {paused ? 'Resume' : 'Pause'}
            </button>
          )}
        </div>
      )}
      {activity && instance && (
        <div className="border-t border-border bg-muted/20 p-4">
          <p className="mb-3 text-[11px] text-muted-foreground">
            Last decision · {when(instance.last_decision)}
          </p>
          <ExperimentActivity
            asset={asset}
            instance={instance.id}
            disabled={disabled || archived}
            command={command}
          />
        </div>
      )}
    </article>
  )
}
