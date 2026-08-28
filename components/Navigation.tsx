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
    <nav className="border-b bg-card">
      <div className="container mx-auto px-3 sm:px-4">
        <div className="flex h-14 items-center gap-3">
          <Link href="/" className="shrink-0 font-bold text-lg">
            <span className="sm:hidden">SW</span>
            <span className="hidden sm:inline">StockWatch</span>
          </Link>

          <div className="ml-auto flex items-center gap-0.5 overflow-x-auto sm:gap-1">
            {navItems.map(({ href, label, icon: Icon }) => {
              const isActive = href === '/' ? pathname === href : pathname.startsWith(href)

              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    'inline-flex shrink-0 items-center gap-2 rounded-md px-2 py-2 text-sm transition-colors sm:px-3',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                  )}
                >
                  <Icon className="h-4 w-4" />
                  <span className="hidden sm:inline">{label}</span>
                </Link>
              )
            })}
          </div>
        </div>
      </div>
    </nav>
  )
}
