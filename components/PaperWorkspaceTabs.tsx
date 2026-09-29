import Link from 'next/link'
export function PaperWorkspaceTabs({
  asset,
  active,
}: {
  asset: 'stocks' | 'bitcoin'
  active: 'manual' | 'automated'
}) {
  return (
    <nav
      aria-label="Paper trading workspaces"
      className="flex flex-wrap gap-2 border-b pb-3 text-sm"
    >
      <Link
        className="sw-button"
        aria-current={active === 'manual' ? 'page' : undefined}
        href={'/manual-paper' + (asset === 'bitcoin' ? '?asset=bitcoin' : '')}
      >
        Manual allocation
      </Link>
      <Link
        className="sw-button"
        aria-current={active === 'automated' ? 'page' : undefined}
        href={asset === 'bitcoin' ? '/crypto?view=paper' : '/portfolio'}
      >
        Automated systems
      </Link>
      {asset === 'stocks' && (
        <Link className="sw-button" href="/portfolio#scanner">
          Legacy scanner lots
        </Link>
      )}
    </nav>
  )
}
