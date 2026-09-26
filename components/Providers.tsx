'use client'

import { Provider as JotaiProvider } from 'jotai'
import { OperatorProvider } from './OperatorSession'

interface ProvidersProps {
  children: React.ReactNode
}

export function Providers({ children }: ProvidersProps) {
  return <JotaiProvider><OperatorProvider>{children}</OperatorProvider></JotaiProvider>
}
