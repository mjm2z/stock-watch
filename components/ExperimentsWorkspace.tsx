'use client'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { Check, FlaskConical, Loader2, Pause, Play } from 'lucide-react'
import { generateId } from '@/lib/utils'
import { useOperator } from './OperatorSession'
import { CompactDisclosure, PagedRows, StatusBadge } from './experiments/CompactDisclosure'
import { ExperimentCard } from './experiments/ExperimentCard'
import { ResearchPanels } from './experiments/ResearchPanels'
import {
  amount,
  date,
  families,
  parsed,
  reason,
  when,
  type Asset,
  type ExperimentData,
} from './experiments/presentation'

export function ExperimentsWorkspace({ asset }: { asset: Asset }) {
  const session = useOperator()
  const [data, setData] = useState<ExperimentData | null>(null),
    [loadError, setLoadError] = useState(''),
    [error, setError] = useState('')
  const [busy, setBusy] = useState(''),
    [submitted, setSubmitted] = useState<{ id: string; action: string } | null>(null)
  const endpoint = '/api/systems/experiments?asset=' + asset
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await fetch(endpoint, { cache: 'no-store', signal }),
          body = await response.json()
        if (!response.ok) throw Error(body.error || 'Experiments are unavailable.')
        if (!signal?.aborted) {
          setData(body)
          setLoadError('')
        }
      } catch (e) {
        if (!signal?.aborted)
          setLoadError(e instanceof Error ? e.message : 'Experiments are unavailable.')
      }
    },
    [endpoint]
  )
  useEffect(() => {
    const controller = new AbortController()
    void refresh(controller.signal)
    const timer = setInterval(() => void refresh(controller.signal), 10000)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [refresh])
  async function command(action: string, extra: Record<string, string> = {}) {
    setBusy(action)
    setError('')
    setSubmitted(null)
    try {
      const response = await fetch('/api/systems/experiments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, asset, requestId: generateId(), ...extra }),
      })
      const body = await response.json()
      if (!response.ok) throw Error(body.error || 'Request failed.')
      setSubmitted({ id: body.id, action })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed.')
    } finally {
      setBusy('')
    }
  }
  const batch = data?.batches.find((item) =>
    ['active', 'paused', 'expired', 'exiting'].includes(item.status)
  )
  const preview = data?.batches.find((item) => item.status === 'preview')
  const current = batch || preview
  const instances = data?.instances.filter((item) => item.batch_id === batch?.id) || []
  const pending = data?.commands.find((item) => item.status === 'pending')
  const submittedResult =
    data?.commands.find((item) => item.id === submitted?.id) ||
    data?.research.find((item) => item.id === submitted?.id)
  const submittedPending = Boolean(submitted && !submittedResult && submitted.action !== 'replay')
  const disabled = Boolean(busy || loadError || !session.authenticated || !data)
  const authorizationDisabled = disabled || Boolean(pending) || submittedPending
  const preparing =
    busy === 'preview' ||
    pending?.action === 'preview' ||
    (submittedPending && submitted?.action === 'preview')
  const approving =
    busy === 'approve' ||
    pending?.action === 'approve' ||
    (submittedPending && submitted?.action === 'approve')
  const previewExpired = Boolean(
    preview?.created && Date.now() >= Date.parse(preview.created) + 30 * 60000
  )
  const paused =
    instances.length > 0 && instances.every((item) => item.paused || item.state === 'paused')
  const riskBlocked = Boolean(
    batch?.risk_reason || ['expired', 'exiting'].includes(batch?.status || '')
  )
  const resultError =
    submittedResult?.status === 'failed'
      ? parsed<{ error?: string }>(submittedResult.result_json, {}).error ||
        ('error' in submittedResult ? submittedResult.error : '') ||
        'The request could not be completed.'
      : ''
  const completed = data?.batches.filter((item) => item.status === 'completed') || []
  return (
    <main className="space-y-6">
      <nav
        aria-label="Systems views"
        className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4 text-xs"
      >
        <div className="flex items-center gap-5">
          <Link
            className="text-muted-foreground hover:text-foreground"
            href={'/systems?asset=' + asset}
          >
            Systems library
          </Link>
          <span aria-current="page" className="font-medium text-primary">
            Paper experiments
          </span>
        </div>
        <div className="inline-flex rounded-lg border border-border bg-card p-1">
          {(['stocks', 'bitcoin'] as const).map((name) => (
            <Link
              key={name}
              href={'/systems?tab=experiments&asset=' + name}
              aria-current={asset === name ? 'page' : undefined}
              className={`rounded-md px-3 py-1.5 ${asset === name ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
            >
              {name === 'stocks' ? 'Stocks' : 'Bitcoin'}
            </Link>
          ))}
        </div>
      </nav>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            <FlaskConical size={13} aria-hidden="true" />
            {asset === 'stocks' ? 'Stocks & ETFs' : 'Bitcoin'} · Paper only
          </div>
          <h1>Paper experiments</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Small trials. Fixed rules. You approve each batch.
          </p>
        </div>
        <StatusBadge tone={batch && !riskBlocked && !paused ? 'good' : 'neutral'}>
          {batch
            ? riskBlocked
              ? 'Entries stopped'
              : paused
                ? 'Entries paused'
                : 'Batch active'
            : preview && !previewExpired
              ? 'Ready for review'
              : 'Trading not started'}
        </StatusBadge>
      </header>
      {(error || loadError || resultError) && (
        <p
          role="alert"
          className="rounded-lg border border-loss/20 bg-loss/5 px-4 py-3 text-sm text-loss"
        >
          {error || loadError || resultError}
        </p>
      )}
      {submitted && !resultError && (
        <p
          role="status"
          className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-xs text-primary"
        >
          {submittedResult?.status === 'succeeded' ? (
            <Check size={14} aria-hidden="true" />
          ) : (
            <Loader2
              size={14}
              className="animate-spin motion-reduce:animate-none"
              aria-hidden="true"
            />
          )}
          {submittedResult?.status === 'succeeded'
            ? 'Request completed.'
            : submitted.action === 'preview'
              ? 'Preparing your batch. Account checks may take a moment.'
              : submitted.action === 'approve'
                ? 'Checking your approval. Trading starts only after the checks pass.'
                : submitted.action === 'replay'
                  ? 'Replay queued. Results will appear in Recent activity.'
                  : 'Request queued. The status updates automatically.'}
        </p>
      )}
      {!data && !loadError && (
        <div
          role="status"
          className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground"
        >
          Loading experiments…
        </div>
      )}
      {data && (
        <>
          <section
            aria-label="Batch approval and controls"
            className="overflow-hidden rounded-xl border border-border bg-card shadow-sm"
          >
            <div className="flex flex-wrap items-center justify-between gap-5 p-5 sm:p-6">
              <div>
                <p className="text-xs text-muted-foreground">
                  {batch ? 'Current paper pool' : 'Planned paper pool'}
                </p>
                <p className="mt-1 text-3xl font-medium tracking-tight tabular-nums">
                  {amount(batch?.equity || '1000')}
                </p>
              </div>
              <dl className="flex flex-wrap gap-5 text-xs sm:gap-8">
                <div>
                  <dt className="text-muted-foreground">Entry cap</dt>
                  <dd className="mt-1.5 font-medium">$50</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Experiments</dt>
                  <dd className="mt-1.5 font-medium">4 + daily control</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{current ? 'Ends' : 'Duration'}</dt>
                  <dd className="mt-1.5 font-medium">
                    {current ? date(current.expires) : '30 days'}
                  </dd>
                </div>
              </dl>
              <div className="flex flex-wrap gap-2">
                {batch ? (
                  <>
                    <button
                      className="sw-button primary"
                      disabled={disabled || (paused && riskBlocked) || batch.status === 'expired'}
                      onClick={() =>
                        void command(paused ? 'resume' : 'pause', { batch_id: batch.id })
                      }
                    >
                      {paused ? (
                        <Play size={14} aria-hidden="true" />
                      ) : (
                        <Pause size={14} aria-hidden="true" />
                      )}
                      {paused ? 'Resume batch' : 'Pause batch'}
                    </button>
                    <button
                      className="sw-button"
                      disabled={disabled}
                      onClick={() => void command('exit_and_pause', { batch_id: batch.id })}
                    >
                      Exit & pause all
                    </button>
                  </>
                ) : (
                  <button
                    className="sw-button primary"
                    disabled={authorizationDisabled}
                    onClick={() =>
                      void command(
                        preview && !previewExpired ? 'approve' : 'preview',
                        preview && !previewExpired
                          ? { batch_id: preview.id, revision: preview.revision }
                          : {}
                      )
                    }
                  >
                    {preparing || approving ? (
                      <Loader2
                        size={14}
                        className="animate-spin motion-reduce:animate-none"
                        aria-hidden="true"
                      />
                    ) : preview && !previewExpired ? (
                      <Check size={14} aria-hidden="true" />
                    ) : (
                      <FlaskConical size={14} aria-hidden="true" />
                    )}
                    {preparing
                      ? 'Preparing preview…'
                      : approving
                        ? 'Approving…'
                        : previewExpired
                          ? 'Refresh preview'
                          : preview
                            ? 'Approve batch'
                            : 'Prepare batch preview'}
                  </button>
                )}
              </div>
            </div>
            <div className="flex flex-wrap justify-between gap-2 border-t border-border bg-muted/25 px-5 py-3 text-[11px] leading-relaxed text-muted-foreground sm:px-6">
              <p>Entries pause at 2% daily loss or 10% drawdown.</p>
              <p>
                {!session.authenticated
                  ? 'Sign in with Operator access to approve or control a batch.'
                  : batch
                    ? `Approved rules stay fixed through ${date(batch.expires)}.`
                    : previewExpired
                      ? 'This preview expired. Refresh it before approving.'
                      : preview
                        ? 'Approval starts all experiments below.'
                        : 'Preparing a preview does not start trading.'}
              </p>
            </div>
          </section>
          {batch?.risk_reason && (
            <p className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4 text-xs leading-relaxed text-amber-700 dark:text-amber-300">
              {reason(batch.risk_reason)} Existing exits remain monitored. Resume cannot reset this
              limit.
            </p>
          )}
          <section aria-label="Experiments" className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold">
                {batch
                  ? 'Your experiments'
                  : preview
                    ? 'Review your experiments'
                    : 'The experiment lineup'}
              </h2>
              <p className="text-xs text-muted-foreground">
                Four $200 strategies · $50 control · $150 reserve
              </p>
            </div>
            <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
              {(current ? current.plan.versions.map((version) => version.family) : families).map(
                (name) => (
                  <ExperimentCard
                    key={`${current?.id || 'planned'}:${name}`}
                    name={name}
                    asset={asset}
                    version={current?.plan.versions.find((version) => version.family === name)}
                    instance={instances.find((item) => item.family === name)}
                    preview={Boolean(preview && !batch && !previewExpired)}
                    riskBlocked={riskBlocked}
                    disabled={disabled}
                    command={command}
                  />
                )
              )}
            </div>
          </section>
          {current && (
            <CompactDisclosure
              title="Batch settings"
              summary={`${asset === 'stocks' ? 'Stocks & ETFs' : 'Bitcoin'} · Fixed rules and execution limits`}
            >
              <div className="grid gap-5 text-xs sm:grid-cols-2">
                <div>
                  <h3 className="mb-2 font-medium">Trading limits</h3>
                  <p className="leading-relaxed text-muted-foreground">
                    Up to four entries per strategy each Eastern day. Long positions only. Limit
                    entries expire after 60 seconds. Exits may use a market order after cancellation
                    is confirmed.
                  </p>
                </div>
                <div>
                  <h3 className="mb-2 font-medium">Timing & cash</h3>
                  <p className="leading-relaxed text-muted-foreground">
                    Decisions follow each completed five-minute bar.{' '}
                    {asset === 'stocks'
                      ? 'Stock sale proceeds wait for settlement.'
                      : 'Bitcoin holds last at most four hours.'}{' '}
                    Batch ends {when(current.expires)}.
                  </p>
                </div>
              </div>
              {batch && (
                <div className="mt-4 flex flex-wrap gap-3 border-t border-border pt-4">
                  <button
                    className="sw-button !min-h-8 !py-1.5 !text-xs"
                    disabled={disabled}
                    onClick={() =>
                      void command('replay', {
                        batch_id: batch.id,
                        start: new Date(Date.now() - 7 * 86400000).toISOString(),
                        end: new Date().toISOString(),
                      })
                    }
                  >
                    Replay last 7 days
                  </button>
                  <button
                    className="sw-button !min-h-8 !py-1.5 !text-xs"
                    disabled={disabled}
                    onClick={() => void command('exit', { batch_id: batch.id })}
                  >
                    Exit positions only
                  </button>
                </div>
              )}
            </CompactDisclosure>
          )}
          <section aria-label="Research and activity" className="space-y-3">
            <h2 className="text-base font-semibold">Research & activity</h2>
            <ResearchPanels
              data={data}
              disabled={authorizationDisabled}
              active={Boolean(batch)}
              command={command}
            />
          </section>
          {completed.length > 0 && (
            <CompactDisclosure
              title="Past batches"
              summary="Completed experiments and their saved decisions."
            >
              <PagedRows
                items={completed}
                pageSize={1}
                label="Past batches"
                render={(old) => (
                  <div key={old.id}>
                    <p className="mb-3 text-xs text-muted-foreground">
                      Ended {date(old.expires)} · Final pool {amount(old.equity)}
                    </p>
                    <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
                      {data.instances
                        .filter((item) => item.batch_id === old.id)
                        .map((item) => (
                          <ExperimentCard
                            key={item.id}
                            name={item.family}
                            asset={asset}
                            instance={item}
                            version={old.plan.versions.find(
                              (version) => version.family === item.family
                            )}
                            archived
                            disabled
                            command={command}
                          />
                        ))}
                    </div>
                  </div>
                )}
              />
            </CompactDisclosure>
          )}
        </>
      )}
    </main>
  )
}
