'use client'

import { useState } from 'react'
import {
  Brain,
  Loader2,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Clock,
  DollarSign,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { StockAnalysis as AnalysisType } from '@/lib/claude'

interface StockAnalysisProps {
  ticker: string
  className?: string
}

interface AnalysisResponse {
  analysis: AnalysisType
  cached: boolean
  cacheAge?: number
}

function ConfidenceIndicator({ level }: { level: number }) {
  const colors = [
    'bg-red-500',
    'bg-orange-500',
    'bg-yellow-500',
    'bg-lime-500',
    'bg-green-500',
  ]

  return (
    <div className="flex items-center gap-1">
      <span className="text-xs text-muted-foreground mr-1">Confidence:</span>
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className={cn(
            'h-2 w-4 rounded-sm',
            i <= level ? colors[level - 1] : 'bg-muted'
          )}
        />
      ))}
      <span className="text-xs text-muted-foreground ml-1">{level}/5</span>
    </div>
  )
}

function formatTimeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)

  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  if (hours < 24) return `${hours}h ago`
  return new Date(timestamp).toLocaleDateString()
}

export function StockAnalysis({ ticker, className }: StockAnalysisProps) {
  const [analysis, setAnalysis] = useState<AnalysisType | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isCached, setIsCached] = useState(false)
  const [showDisclaimer, setShowDisclaimer] = useState(false)

  const runAnalysis = async (forceRefresh = false) => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, forceRefresh }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'Analysis failed')
      }

      const data: AnalysisResponse = await response.json()
      setAnalysis(data.analysis)
      setIsCached(data.cached)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setIsLoading(false)
    }
  }

  // Initial state - show analyze button
  if (!analysis && !isLoading && !error) {
    return (
      <div className={cn('rounded-lg border bg-card p-6', className)}>
        <div className="text-center py-8">
          <Brain className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
          <h3 className="text-lg font-semibold mb-2">AI Stock Analysis</h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-md mx-auto">
            Get a balanced analysis of {ticker} powered by Claude AI,
            including bullish and bearish factors, technical setup, and catalysts.
          </p>
          <button
            onClick={() => runAnalysis()}
            className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <Brain className="h-5 w-5" />
            Analyze {ticker}
          </button>
          <p className="text-xs text-muted-foreground mt-4">
            Estimated cost: ~$0.01-0.05 per analysis
          </p>
        </div>
      </div>
    )
  }

  // Loading state
  if (isLoading) {
    return (
      <div className={cn('rounded-lg border bg-card p-6', className)}>
        <div className="text-center py-12">
          <Loader2 className="h-10 w-10 mx-auto text-primary animate-spin mb-4" />
          <p className="text-muted-foreground">
            Analyzing {ticker}...
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            This usually takes 5-10 seconds
          </p>
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className={cn('rounded-lg border bg-card p-6', className)}>
        <div className="text-center py-8">
          <AlertTriangle className="h-10 w-10 mx-auto text-destructive mb-4" />
          <p className="text-destructive mb-4">{error}</p>
          <button
            onClick={() => runAnalysis()}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <RefreshCw className="h-4 w-4" />
            Try Again
          </button>
        </div>
      </div>
    )
  }

  // Analysis display
  if (!analysis) return null

  return (
    <div className={cn('rounded-lg border bg-card', className)}>
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-3">
          <Brain className="h-5 w-5 text-primary" />
          <h3 className="font-semibold">AI Analysis</h3>
          {isCached && (
            <span className="text-xs bg-muted px-2 py-0.5 rounded">Cached</span>
          )}
        </div>
        <button
          onClick={() => runAnalysis(true)}
          disabled={isLoading}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          title="Re-analyze (bypass cache)"
        >
          <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
          Re-analyze
        </button>
      </div>

      <div className="p-4 space-y-6">
        {/* Meta info */}
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <ConfidenceIndicator level={analysis.confidenceLevel} />
          <div className="flex items-center gap-1 text-muted-foreground">
            <Clock className="h-4 w-4" />
            {formatTimeAgo(analysis.timestamp)}
          </div>
          <div className="flex items-center gap-1 text-muted-foreground">
            <DollarSign className="h-4 w-4" />
            ~${analysis.estimatedCost.toFixed(4)}
          </div>
        </div>

        {/* Investment Thesis */}
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-2">
            Investment Thesis
          </h4>
          <p className="text-sm leading-relaxed">{analysis.investmentThesis}</p>
        </div>

        {/* Bullish / Bearish Grid */}
        <div className="grid gap-4 md:grid-cols-2">
          {/* Bullish Factors */}
          <div className="rounded-lg bg-gain/10 p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="h-4 w-4 text-gain" />
              <h4 className="font-medium text-gain">Bullish Factors</h4>
            </div>
            <ul className="space-y-2">
              {analysis.bullishFactors.map((factor, i) => (
                <li key={i} className="text-sm flex items-start gap-2">
                  <span className="text-gain mt-1">•</span>
                  <span>{factor}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Bearish Factors */}
          <div className="rounded-lg bg-loss/10 p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingDown className="h-4 w-4 text-loss" />
              <h4 className="font-medium text-loss">Bearish Factors</h4>
            </div>
            <ul className="space-y-2">
              {analysis.bearishFactors.map((factor, i) => (
                <li key={i} className="text-sm flex items-start gap-2">
                  <span className="text-loss mt-1">•</span>
                  <span>{factor}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Technical Setup */}
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-2">
            Technical Setup
          </h4>
          <p className="text-sm leading-relaxed">{analysis.technicalSetup}</p>
        </div>

        {/* Catalysts */}
        {analysis.catalysts.length > 0 && (
          <div>
            <h4 className="text-sm font-medium text-muted-foreground mb-2">
              Upcoming Catalysts
            </h4>
            <ul className="flex flex-wrap gap-2">
              {analysis.catalysts.map((catalyst, i) => (
                <li
                  key={i}
                  className="text-sm bg-muted px-3 py-1 rounded-full"
                >
                  {catalyst}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Bottom Line */}
        <div className="rounded-lg bg-muted p-4">
          <h4 className="text-sm font-medium mb-2">Bottom Line</h4>
          <p className="text-sm leading-relaxed">{analysis.bottomLine}</p>
        </div>

        {/* Disclaimer */}
        <div className="border-t pt-4">
          <button
            onClick={() => setShowDisclaimer(!showDisclaimer)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <AlertTriangle className="h-3 w-3" />
            Important Disclaimer
            {showDisclaimer ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
          </button>
          {showDisclaimer && (
            <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
              {analysis.disclaimer}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
