import { Suspense } from 'react'
import { DashboardRefresh } from '@/components/dashboard/DashboardRefresh'
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { Providers } from '@/components/Providers'
import { Navigation } from '@/components/Navigation'

const inter = Inter({ subsets: ['latin'], variable: '--font-geist-sans' })

export const metadata: Metadata = {
  title: 'Stock Watch - Market Intelligence',
  description: 'Transparent S&P 500 signals, paper trading, and backtest analytics',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`}>
        <Providers>
          <div className="min-h-screen bg-background">
            <a href="#main-content" className="sr-only focus:not-sr-only focus:block focus:p-3">
              Skip to main content
            </a>
            <Suspense fallback={<div className="h-24 border-b" />}>
              <Navigation />
            </Suspense>
            <div id="main-content" tabIndex={-1}>
              {children}
            </div>
            <footer className="container mx-auto flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 text-xs text-muted-foreground">
              <span>
                Paper trading · Stocks: Eastern time · Bitcoin: UTC · Saved results refresh every
                minute
              </span>
              <DashboardRefresh />
            </footer>
          </div>
        </Providers>
      </body>
    </html>
  )
}
