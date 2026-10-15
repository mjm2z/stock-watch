'use client'
import { useCallback, useEffect, useState } from 'react'
import { CompactDisclosure, PagedRows, StatusBadge } from './CompactDisclosure'
import { human, reason, when, type Asset, type Command, type Detail } from './presentation'

export function ExperimentActivity({
  asset,
  instance,
  disabled,
  command,
}: {
  asset: Asset
  instance: string
  disabled: boolean
  command: Command
}) {
  const [detail, setDetail] = useState<Detail | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false)
  const endpoint = `/api/systems/experiments?asset=${asset}&instance=${instance}`
  const load = useCallback(
    async (signal?: AbortSignal, before?: string) => {
      setLoading(true)
      try {
        const response = await fetch(
          endpoint + (before ? '&before=' + encodeURIComponent(before) : ''),
          { cache: 'no-store', signal }
        )
        const body = await response.json()
        if (!response.ok) throw Error(body.error || 'Activity unavailable.')
        if (!signal?.aborted) {
          setDetail((old) =>
            before && old ? { ...body, decisions: [...old.decisions, ...body.decisions] } : body
          )
          setError('')
        }
      } catch (e) {
        if (!signal?.aborted) setError(e instanceof Error ? e.message : 'Activity unavailable.')
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [endpoint]
  )
  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])
  return (
    <div className="space-y-3 text-xs">
      {error && (
        <p role="alert" className="text-loss">
          {error}
        </p>
      )}
      {loading && !detail && (
        <p role="status" className="text-muted-foreground">
          Loading activity…
        </p>
      )}
      {detail && (
        <>
          <p className="text-muted-foreground">
            {detail.positions
              .filter((p) => Number(p.quantity) > 0)
              .map(
                (p) =>
                  `${p.symbol} · ${Number(p.quantity).toLocaleString('en-US', { maximumFractionDigits: 6 })} ${asset === 'stocks' ? 'shares' : 'BTC'} · exit by ${when(p.exit_due)}`
              )
              .join(' / ') || 'No open positions.'}
          </p>
          {detail.orders.some((order) => order.error) && (
            <CompactDisclosure
              title="Order issues"
              compact
              badge={
                <StatusBadge tone="attention">
                  {detail.orders.filter((order) => order.error).length}
                </StatusBadge>
              }
            >
              <PagedRows
                items={detail.orders.filter((order) => order.error)}
                label="Order issues"
                render={(order) => (
                  <p key={order.id} className="py-2 leading-relaxed text-loss">
                    {order.symbol}: {order.error}
                  </p>
                )}
              />
            </CompactDisclosure>
          )}
          <PagedRows
            items={detail.decisions}
            label="Decision history"
            pageSize={3}
            render={(d) => (
              <div key={d.id} className="py-2 first:pt-0">
                <CompactDisclosure
                  compact
                  title={`${d.symbol} · ${human(d.outcome)}`}
                  summary={when(d.cutoff)}
                >
                  <p className="leading-relaxed">{reason(d.reason)}</p>
                  <p className="mt-2 text-muted-foreground">
                    {d.evidence.bars?.length || 0} price bars · {d.evidence.news?.length || 0} news
                    items
                  </p>
                  <a
                    className="mt-3 inline-block text-primary underline underline-offset-4"
                    href={`/api/systems/experiments?asset=${asset}&decision=${d.id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open saved evidence
                  </a>
                </CompactDisclosure>
              </div>
            )}
          />
          {!detail.decisions.length && (
            <p className="text-muted-foreground">No decisions recorded yet.</p>
          )}
          {detail.next && (
            <button
              className="text-primary"
              disabled={loading}
              onClick={() => void load(undefined, detail.next!)}
            >
              Load earlier decisions
            </button>
          )}
          {detail.gaps?.length > 0 && (
            <CompactDisclosure
              compact
              title="Collection gaps"
              badge={<StatusBadge>{detail.gaps.length}</StatusBadge>}
            >
              <PagedRows
                items={detail.gaps}
                label="Collection gaps"
                render={(g) => (
                  <p key={g.start} className="py-2 text-muted-foreground">
                    {when(g.start)} – {when(g.end)}
                    <span className="mt-1 block leading-relaxed">{g.reason}</span>
                  </p>
                )}
              />
            </CompactDisclosure>
          )}
        </>
      )}
      <div className="flex flex-wrap gap-3 border-t border-border pt-3">
        <button
          disabled={loading}
          className="rounded text-muted-foreground hover:text-foreground disabled:opacity-40"
          onClick={() => void load()}
        >
          Refresh
        </button>
        <button
          disabled={disabled}
          className="rounded text-loss disabled:opacity-40"
          onClick={() => void command('exit_and_pause', { instance_id: instance })}
        >
          Exit positions & pause
        </button>
      </div>
    </div>
  )
}
