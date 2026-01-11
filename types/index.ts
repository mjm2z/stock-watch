/**
 * Core Stock Types for AI Stock Analysis Dashboard
 */

// Basic stock information returned from search
export interface Stock {
  ticker: string
  name: string
  price: number
  change: number
  changePercent: number
  marketCap: number
  sector: string
  exchange: string
  volume?: number
  avgVolume?: number
}

// Real-time quote data
export interface Quote {
  ticker: string
  price: number
  open: number
  high: number
  low: number
  previousClose: number
  volume: number
  change: number
  changePercent: number
  timestamp: string
}

// Company fundamentals
export interface Fundamentals {
  ticker: string
  name: string
  description?: string
  sector: string
  industry: string
  marketCap: number
  pe: number | null
  eps: number | null
  revenue: number | null
  revenueGrowth: number | null
  profitMargin: number | null
  debtToEquity: number | null
  dividendYield: number | null
  beta: number | null
  fiftyTwoWeekHigh: number
  fiftyTwoWeekLow: number
  avgVolume: number
  sharesOutstanding: number
}

// Historical price data for charts
export interface PriceData {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

// Paper trade / hypothetical portfolio entry
export interface PaperTrade {
  id: string
  type: 'paper' | 'real'
  ticker: string
  entryDate: string
  entryPrice: number
  currentPrice: number
  shares: number
  investment: number
  profitLoss: number
  profitLossPct: number
  holdPeriod: HoldPeriod
  targetPrice?: number
  notes?: string
  status: 'active' | 'closed'
  closedDate?: string
  closedPrice?: number
  // Audit trail fields (for tracking AI recommendations)
  claudePrompt?: string
  claudeResponse?: string
  analysisTimestamp?: string
  dataFreshness?: string
  marketContext?: MarketContext
}

export type HoldPeriod = '1_week' | '1_month' | '3_months' | '6_months' | '1_year'

// Watchlist item
export interface WatchlistItem {
  ticker: string
  addedAt: string
  notes?: string
  lastAnalyzed?: string
}

// Market context for analysis
export interface MarketContext {
  vix: number
  tenYearYield: number
  dxy: number
  sp500: number
  sp500Change: number
  regime: 'risk-on' | 'risk-off' | 'neutral'
  timestamp: string
}

// AI Analysis result
export interface StockAnalysis {
  ticker: string
  timestamp: string
  dataFreshness: string
  confidence: 1 | 2 | 3 | 4 | 5
  thesis: string
  bullishFactors: string[]
  bearishFactors: string[]
  technicalSetup: string
  catalysts: string[]
  bottomLine: string
  marketContext: MarketContext
  costUsd: number
  cached: boolean
}

// API cost tracking
export interface ApiCosts {
  currentMonth: string
  claudeCosts: number
  fmpCalls: number
  analyses: number
  budget: number
  history: Array<{ month: string; total: number }>
}

// Alert types for Phase 2
export interface Alert {
  id: string
  ticker: string
  type: 'price' | 'technical' | 'event' | 'volume'
  condition: AlertCondition
  createdAt: string
  triggeredAt?: string
  status: 'active' | 'triggered' | 'dismissed'
  notificationSent: boolean
}

export interface AlertCondition {
  targetPrice?: number
  direction?: 'above' | 'below'
  indicator?: 'ma50' | 'ma200' | 'rsi' | 'golden_cross' | 'death_cross'
  volumeMultiple?: number
  eventType?: 'earnings' | 'dividend' | 'split'
}

// Trade journal entry for Phase 2
export interface TradeJournalEntry {
  tradeId: string
  preTradeThesis: string
  preTradeConfidence: number
  preTradeEmotions: TradeEmotion[]
  preTradeChecklist: {
    reviewedAnalysis: boolean
    gotSecondOpinion: boolean
    sizeAppropriate: boolean
    hasExitPlan: boolean
  }
  holdingNotes: Array<{ date: string; note: string }>
  postTradeReview?: {
    whatWentWell: string
    whatWentWrong: string
    lessonsLearned: string
    wouldTakeAgain: boolean
    actualVsExpected: 'better' | 'worse' | 'as_expected'
  }
}

export type TradeEmotion = 'confident' | 'anxious' | 'fomo' | 'patient' | 'impulsive'

// Portfolio metrics
export interface PortfolioMetrics {
  totalTrades: number
  activeTrades: number
  winRate: number
  avgGain: number
  avgLoss: number
  totalInvested: number
  currentValue: number
  totalProfitLoss: number
  totalProfitLossPct: number
}
