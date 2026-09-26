'use client'
import Link from 'next/link'
import { usePathname, useSearchParams } from 'next/navigation'
import {
  Activity,
  BriefcaseBusiness,
  FlaskConical,
  LayoutDashboard,
  Search,
  ServerCog,
  ChartNoAxesCombined,
  Moon,
  Sun,
  Menu,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { OperatorControls } from './OperatorSession'
const sections = [
  ['overview', 'Overview', LayoutDashboard],
  ['systems', 'Systems', FlaskConical],
  ['backtesting', 'Backtesting', ChartNoAxesCombined],
  ['paper', 'Paper trading', BriefcaseBusiness],
  ['signals', 'Signals', Activity],
  ['research', 'Research', Search],
  ['operations', 'Operations', ServerCog],
] as const
export function Navigation() {
  const sidebar = useRef<HTMLElement>(null)
  const path = usePathname(),
    params = useSearchParams()
  const crypto =
    path === '/crypto' ||
    path === '/bitcoin' ||
    params.get('asset') === 'bitcoin' ||
    params.get('asset') === 'crypto'
  const section =
    path === '/systems'
      ? 'systems'
      : path === '/backtesting' || path === '/backtests'
        ? 'backtesting'
        : path === '/portfolio'
          ? 'paper'
          : path === '/signals'
            ? 'signals'
            : path === '/operations'
              ? 'operations'
              : path === '/research' || path === '/watchlist' || path.startsWith('/stock/')
                ? 'research'
                : params.get('view') === 'blockchain'
                  ? 'research'
                  : params.get('view') || 'overview'
  const [open, setOpen] = useState(false),
    [theme, setTheme] = useState('dark')
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme || 'dark')
  }, [])
  useEffect(() => {
    setOpen(false)
  }, [path, params])
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const links = () =>
      Array.from(
        sidebar.current?.querySelectorAll<HTMLElement>('a[href],button:not([disabled])') || []
      ).filter((el) => el.getClientRects().length)
    links()[0]?.focus()
    const close = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
      if (e.key === 'Tab') {
        const items = links(),
          first = items[0],
          last = items.at(-1)
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last?.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first?.focus()
        }
      }
    }
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('keydown', close)
      previous?.focus()
    }
  }, [open])
  function href(key: string, isCrypto = crypto) {
    if (key === 'systems' || key === 'backtesting')
      return '/' + key + (isCrypto ? '?asset=bitcoin' : '')
    if (isCrypto)
      return (
        '/crypto' + (key === 'overview' ? '' : '?view=' + (key === 'research' ? 'blockchain' : key))
      )
    return (
      (
        {
          overview: '/',
          paper: '/portfolio',
          signals: '/signals',
          research: '/research',
          operations: '/operations',
        } as Record<string, string>
      )[key] || '/'
    )
  }
  function toggle() {
    const value = theme === 'dark' ? 'light' : 'dark'
    setTheme(value)
    document.documentElement.dataset.theme = value
    document.documentElement.classList.toggle('dark', value === 'dark')
    document.cookie = `stockwatch_theme=${value}; Path=/; Max-Age=31536000; SameSite=Lax`
  }
  return (
    <>
      <header className="sw-topbar">
        <div className="flex items-center gap-3">
          <button
            className="sw-mobile-menu"
            aria-label="Open navigation"
            aria-expanded={open}
            onClick={() => setOpen(true)}
          >
            <Menu size={20} />
          </button>
          <span className="text-muted-foreground">Workspace</span>
          <span aria-hidden="true">/</span>
          <strong>
            {crypto ? 'Crypto' : 'Stocks'} ·{' '}
            {sections.find((x) => x[0] === section)?.[1] || 'Overview'}
          </strong>
        </div>
        <div className="flex items-center gap-3">
          <span className="sw-paper-label">Paper trading only</span>
          <OperatorControls />
        </div>
      </header>
      {open && (
        <button
          className="sw-nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        />
      )}
      <aside
        ref={sidebar}
        className={'sw-sidebar' + (open ? ' is-open' : '')}
        aria-label="Workspace navigation"
      >
        <Link href="/" className="sw-brand">
          <img src="/icon.svg" width="34" height="34" alt="" />
          <span>
            Stock<span className="font-normal text-muted-foreground">Watch</span>
            <small>RESEARCH & PAPER TRADING</small>
          </span>
        </Link>
        <button
          className="sw-mobile-close"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        >
          <X size={20} />
        </button>
        <div className="sw-asset-switch" aria-label="Asset context">
          <Link href={href(section, false)} aria-current={!crypto ? 'true' : undefined}>
            Stocks
          </Link>
          <Link href={href(section, true)} aria-current={crypto ? 'true' : undefined}>
            Crypto
          </Link>
        </div>
        <p className="sw-nav-label">WORKSPACE</p>
        <nav aria-label="Main navigation">
          {sections.map(([key, label, Icon]) => (
            <Link key={key} href={href(key)} aria-current={section === key ? 'page' : undefined}>
              <Icon size={17} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="sw-sidebar-bottom">
          <div>
            <strong>Local workspace</strong>
            <small>{crypto ? 'BTC/USD · UTC' : 'US equities · Eastern time'}</small>
          </div>
          <button
            aria-label={'Switch to ' + (theme === 'dark' ? 'light' : 'dark') + ' theme'}
            onClick={toggle}
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </aside>
    </>
  )
}
