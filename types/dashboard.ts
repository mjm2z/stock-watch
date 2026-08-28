export interface DashboardPillar {
  name: string
  score: number | null
  weight: number
  weightedPoints: number
  available: boolean
}

export interface DashboardSignal {
  id: string
  symbol: string
  companyName: string | null
  horizonTradingDays: number
  asOf: string
  score: number
  completeness: number
  risk: 'low' | 'medium' | 'high'
  decision: string
  explanation: string
  reasons: string[]
  pillars: DashboardPillar[]
  orderStatus: string | null
  notionalUsd: number | null
  lotStatus: string | null
  netReturn: number | null
  excessReturn: number | null
  beatSpy: boolean | null
  currentPrice: number | null
}

export interface DashboardScan {
  id: string
  type: string
  scheduledFor: string
  status: string
  strategyName: string
  strategyStatus: string
  qualifiedSignals: number
  totalSignals: number
  error: string | null
}

export interface DashboardOverview {
  available: boolean
  unavailableReason?: string
  generatedAt: string
  strategyStatus: string | null
  latestScan: DashboardScan | null
  recentScans: DashboardScan[]
  topSignals: DashboardSignal[]
  metrics: {
    qualifiedSignals: number
    openLots: number
    deployedNotionalUsd: number
    realizedPnlUsd: number
    positiveRate: number | null
    beatSpyRate: number | null
    completedOutcomes: number
    failedJobs: number
  }
}

export interface DashboardPortfolioLot {
  id: string
  symbol: string
  horizonTradingDays: number
  status: string
  score: number
  entryNotionalUsd: number
  entryPrice: number | null
  entryQuantity: number | null
  openedAt: string | null
  targetExitAt: string | null
  closedAt: string | null
  exitPrice: number | null
  exitQuantity: number | null
  realizedReturn: number | null
  orderStatus: string
  exitOrderStatus: string | null
}

export interface DashboardPortfolio {
  lots: DashboardPortfolioLot[]
  totals: {
    lots: number
    openLots: number
    deployedNotionalUsd: number
    contributedCapitalUsd: number
    equityUsd: number
    realizedPnlUsd: number
    unrealizedPnlUsd: number
    spyValueUsd: number | null
    excessVsSpyUsd: number | null
    portfolioReturn: number | null
    spyReturn: number | null
    excessReturn: number | null
  }
  history: Array<{
    observedAt: string
    equity: number
    contributedCapital: number
    spyValue: number | null
    realizedPnl: number
    unrealizedPnl: number
  }>
}

export interface DashboardBacktest {
  id: string
  strategyName: string
  status: string
  datasetVersion: string
  datasetSha256: string
  featureSetVersion: string
  survivorshipBiased: boolean
  costBps: number
  createdAt: string
  completedAt: string | null
  metrics: Record<string, unknown>
  tradeCount: number
  rejectionCount: number
  splitCount: number
}

export interface DashboardOperations {
  brokerReconciliation: {
    capturedAt: string
    status: string
    accountStatus: string
    cashUsd: number
    equityUsd: number
    expectedPositions: Record<string, unknown>
    actualPositions: Record<string, unknown>
    discrepancies: Array<Record<string, unknown>>
    corporateActions: Array<Record<string, unknown>>
  } | null
  runs: Array<{
    id: string
    command: string
    status: string
    startedAt: string
    completedAt: string | null
    heartbeatAt: string
    durationSeconds: number
    progressCurrent: number | null
    progressTotal: number | null
    message: string | null
    context: Record<string, unknown>
    result: Record<string, unknown>
    errorType: string | null
    errorMessage: string | null
    exceptionChain: Array<Record<string, unknown>>
    traceback: string | null
    host: string
    processId: number
  }>
  jobs: Array<{
    id: string
    type: string
    status: string
    scheduledFor: string
    attempt: number
    error: string | null
  }>
  ingestions: Array<{
    id: number
    dataset: string
    provider: string
    status: string
    completedAt: string | null
    rowCount: number
    error: string | null
  }>
}
