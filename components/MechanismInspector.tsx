'use client'
import Link from 'next/link'
import { useEffect, useState } from 'react'
export function MechanismInspector() {
  const [checks, setChecks] = useState<{ name: string; data: any }[]>([])
  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      const results = await Promise.all(
        ['market-feed', 'execution', 'notifications'].map(async (name) => {
          try {
            const r = await fetch('/api/health/' + name, {
              signal: controller.signal,
              cache: 'no-store',
            })
            return { name, data: await r.json() }
          } catch {
            return { name, data: { healthy: false, error: 'Unavailable' } }
          }
        })
      )
      if (!controller.signal.aborted) setChecks(results)
    }
    void load()
    const timer = setInterval(load, 30000)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [])
  return (
    <section className="sw-panel space-y-4">
      <h2 className="text-xl font-semibold">How an order happens</h2>
      <p className="text-sm">
        Data → Features and rules → Decision → Qualification → Authorization → Order →
        Reconciliation
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        {checks.map((c) => (
          <details key={c.name} className="rounded border p-3">
            <summary className="font-semibold">
              {c.name}:{' '}
              {c.data.healthy
                ? 'Healthy'
                : c.data.configured === false
                  ? 'Unconfigured / unavailable'
                  : 'Unavailable or stale'}
            </summary>
            <pre className="mt-3 max-h-52 overflow-auto text-xs">
              {JSON.stringify(c.data, null, 2)}
            </pre>
          </details>
        ))}
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="font-semibold">Data quality</dt>
          <dd>
            Source, coverage, warmup and corporate actions determine whether inputs can be
            interpreted. Check Data capabilities below.
          </dd>
        </div>
        <div>
          <dt className="font-semibold">Research evidence</dt>
          <dd>
            Historical simulations, forward observations and paper fills are separate evidence
            classes. A preview never qualifies a system.
          </dd>
        </div>
        <div>
          <dt className="font-semibold">Operational readiness</dt>
          <dd>
            Feed, owner and notification health are independent. Missing credentials are shown as
            unconfigured.
          </dd>
        </div>
        <div>
          <dt className="font-semibold">Execution authority</dt>
          <dd>
            Existing policy, account identity, budgets and confirmations decide whether an
            instruction can proceed. Chart toggles and experiment reviews change no authority.
          </dd>
        </div>
      </dl>
      <div className="flex flex-wrap gap-3">
        <a className="sw-button" href="/activity">
          Inspect recorded transitions
        </a>
        <Link className="sw-button" href="/systems">
          System rules & authority
        </Link>
      </div>
    </section>
  )
}
