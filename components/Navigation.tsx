'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  Activity,
  BriefcaseBusiness,
  FlaskConical,
  LayoutDashboard,
  Search,
  ServerCog,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { href: '/', label: 'Overview', icon: LayoutDashboard },
  { href: '/signals', label: 'Signals', icon: Activity },
  { href: '/portfolio', label: 'Paper', icon: BriefcaseBusiness },
  { href: '/backtests', label: 'Backtests', icon: FlaskConical },
  { href: '/operations', label: 'Ops', icon: ServerCog },
  { href: '/research', label: 'Research', icon: Search },
]

export function Navigation() {
  const pathname = usePathname()

  return (
    <nav aria-label="Main navigation" className="border-b bg-card">
      <div className="container mx-auto px-3 lg:px-4">
        <div className="flex flex-col items-stretch gap-2 py-2 lg:flex-row lg:items-center">
          <Link href="/" className="shrink-0 font-bold text-lg">
            <span className="lg:hidden">SW</span>
            <span className="hidden lg:inline">StockWatch</span>
          </Link>

          <div className="grid grid-cols-6 gap-0.5 lg:ml-auto lg:flex lg:items-center lg:gap-1">
            {navItems.map(({ href, label, icon: Icon }) => {
              const isActive =
                href === '/'
                  ? pathname === href
                  : pathname.startsWith(href) ||
                    (href === '/research' &&
                      (pathname.startsWith('/stock/') || pathname === '/watchlist'))

              return (
                <Link
                  key={href}
                  href={href}
                  aria-label={label === 'Ops' ? 'Operations' : label}
                  aria-current={isActive ? 'page' : undefined}
                  className={cn(
                    'inline-flex min-h-11 flex-col items-center justify-center gap-1 rounded-md px-1 py-2 text-[11px] transition-colors lg:flex-row lg:gap-2 lg:px-3 lg:text-sm',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                  )}
                >
                  <Icon className="h-4 w-4" />
                  <span>{label}</span>
                </Link>
              )
            })}
          </div>
        </div>
      </div>
    </nav>
  )
}
