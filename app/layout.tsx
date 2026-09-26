import { Suspense } from 'react'
import { cookies } from 'next/headers'
import { DashboardRefresh } from '@/components/dashboard/DashboardRefresh'
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { Providers } from '@/components/Providers'
import { Navigation } from '@/components/Navigation'

const inter = Inter({ subsets: ['latin'], variable: '--font-geist-sans' })

export const metadata: Metadata = {
  title: { default: 'StockWatch | Research workspace', template: '%s | StockWatch' },
  applicationName: 'StockWatch',
  description:
    'Stocks and crypto research, visual trading systems, backtests, and paper portfolios',
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const theme = (await cookies()).get('stockwatch_theme')?.value === 'light' ? 'light' : 'dark'
  return (
    <html
      lang="en"
      data-theme={theme}
      className={theme === 'dark' ? 'dark' : ''}
      suppressHydrationWarning
    >
      <body className={`${inter.variable} font-sans antialiased`}>
        <Providers>
          <div className="min-h-screen bg-background">
            <a href="#main-content" className="sr-only focus:not-sr-only focus:block focus:p-3">
              Skip to main content
            </a>
            <Suspense fallback={<div className="sw-topbar" />}>
              <Navigation />
            </Suspense>
            <div className="sw-content" id="main-content" tabIndex={-1}>
              {children}
            </div>
            <footer className="sw-footer">
              <span>
                Paper trading · Stocks: Eastern time · Crypto: UTC · Saved results refresh every
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
