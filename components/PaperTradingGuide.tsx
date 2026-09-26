import Link from 'next/link'
export function PaperTradingGuide({ asset }: { asset: 'stocks' | 'bitcoin' }) {
  const query = asset === 'bitcoin' ? '?asset=bitcoin' : ''
  return (
    <section className="sw-panel">
      <div className="sw-panel-heading">
        <div>
          <h2>From a system to paper trading</h2>
          <p>
            Paper orders simulate execution through the broker. Historical tests and forward
            observation do not place orders.
          </p>
        </div>
        <Link className="sw-button" href={'/systems' + query}>
          Manage systems
        </Link>
      </div>
      <ol className="grid gap-5 md:grid-cols-3">
        <li>
          <strong>1. Define and test</strong>
          <p className="sw-muted mt-2">
            Publish immutable rules, then review returns, costs, drawdowns, and modeled fills in{' '}
            <Link className="underline" href={'/backtesting' + query}>
              Backtesting
            </Link>
            .
          </p>
        </li>
        <li>
          <strong>2. Observe and prepare</strong>
          <p className="sw-muted mt-2">
            {asset === 'bitcoin'
              ? 'Collect forward evidence, complete qualification, and fund the separate Crypto paper account.'
              : 'Collect at least 20 stock sessions and review the existing account, orders, and position ownership.'}{' '}
            Trading workers must be enabled in Operations.
          </p>
        </li>
        <li>
          <strong>3. Explicitly start</strong>
          <p className="sw-muted mt-2">
            Choose the exact system version and confirm Start paper trading. The worker rechecks
            prerequisites. Existing positions and account-wide risk limits remain authoritative.
          </p>
        </li>
      </ol>
    </section>
  )
}
