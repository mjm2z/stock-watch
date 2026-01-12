import Anthropic from '@anthropic-ai/sdk'
import type { Quote, Fundamentals } from '@/types'

/**
 * Claude API client for stock analysis
 */

// Analysis result type
export interface StockAnalysis {
  ticker: string
  timestamp: string
  dataFreshness: string
  confidenceLevel: number // 1-5 scale
  investmentThesis: string
  bullishFactors: string[]
  bearishFactors: string[]
  technicalSetup: string
  catalysts: string[]
  bottomLine: string
  disclaimer: string
  // Cost tracking
  inputTokens: number
  outputTokens: number
  estimatedCost: number
}

// Claude pricing (as of 2024) - Claude 3.5 Sonnet
const CLAUDE_PRICING = {
  inputPerMillion: 3.0,
  outputPerMillion: 15.0,
  cachedInputPerMillion: 0.30, // 90% savings with prompt caching
}

/**
 * Calculate estimated cost from token usage
 */
export function calculateCost(
  inputTokens: number,
  outputTokens: number,
  cachedInputTokens: number = 0
): number {
  const uncachedInputTokens = inputTokens - cachedInputTokens
  const inputCost = (uncachedInputTokens / 1_000_000) * CLAUDE_PRICING.inputPerMillion
  const cachedCost = (cachedInputTokens / 1_000_000) * CLAUDE_PRICING.cachedInputPerMillion
  const outputCost = (outputTokens / 1_000_000) * CLAUDE_PRICING.outputPerMillion
  return inputCost + cachedCost + outputCost
}

/**
 * Get the Anthropic client
 */
function getClient(): Anthropic {
  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    throw new Error('ANTHROPIC_API_KEY environment variable is not set')
  }
  return new Anthropic({ apiKey })
}

/**
 * Build the system prompt for stock analysis
 * This prompt is designed to be cached and reused across analyses
 */
function getSystemPrompt(): string {
  return `You are an experienced financial analyst providing balanced, educational stock analysis. Your role is to help individual investors understand stocks better, not to give financial advice.

IMPORTANT GUIDELINES:
1. Always present balanced analysis with both bullish and bearish perspectives
2. Use probabilistic language ("may", "could", "tends to") rather than absolutes
3. Acknowledge uncertainty and limitations of analysis
4. Never recommend specific buy/sell actions - instead describe setups and scenarios
5. Always include risks and potential downsides
6. Reference actual data when available, acknowledge when speculating

OUTPUT FORMAT:
Provide your analysis in the following JSON structure:
{
  "confidenceLevel": <1-5 number, where 1=very uncertain, 5=high confidence in analysis quality>,
  "investmentThesis": "<2-3 sentence summary of the core investment case>",
  "bullishFactors": ["<factor 1>", "<factor 2>", "<factor 3>"],
  "bearishFactors": ["<factor 1>", "<factor 2>", "<factor 3>"],
  "technicalSetup": "<Brief description of current price action, trend, and key levels>",
  "catalysts": ["<upcoming event 1>", "<upcoming event 2>"],
  "bottomLine": "<1-2 sentence balanced conclusion with 'lean' language>"
}

Remember: You're educating, not advising. Help users understand the stock, don't tell them what to do.`
}

/**
 * Build the user prompt with stock-specific data
 */
function buildUserPrompt(
  ticker: string,
  quote: Quote,
  fundamentals: Fundamentals | null
): string {
  const parts = [
    `Analyze ${ticker} based on the following data:`,
    '',
    '## Current Quote',
    `- Price: $${quote.price.toFixed(2)}`,
    `- Change: ${quote.change >= 0 ? '+' : ''}$${quote.change.toFixed(2)} (${quote.changePercent >= 0 ? '+' : ''}${quote.changePercent.toFixed(2)}%)`,
    `- Day Range: $${quote.low.toFixed(2)} - $${quote.high.toFixed(2)}`,
    `- Previous Close: $${quote.previousClose.toFixed(2)}`,
  ]

  if (fundamentals) {
    parts.push(
      '',
      '## Company Info',
      `- Name: ${fundamentals.name}`,
      `- Sector: ${fundamentals.sector}`,
      `- Industry: ${fundamentals.industry}`,
    )

    if (fundamentals.marketCap > 0) {
      const marketCapB = fundamentals.marketCap / 1_000_000_000
      parts.push(`- Market Cap: $${marketCapB.toFixed(2)}B`)
    }

    if (fundamentals.pe) {
      parts.push(`- P/E Ratio: ${fundamentals.pe.toFixed(2)}`)
    }

    if (fundamentals.eps) {
      parts.push(`- EPS: $${fundamentals.eps.toFixed(2)}`)
    }

    if (fundamentals.dividendYield) {
      parts.push(`- Dividend Yield: ${fundamentals.dividendYield.toFixed(2)}%`)
    }

    if (fundamentals.fiftyTwoWeekHigh > 0 && fundamentals.fiftyTwoWeekLow > 0) {
      parts.push(`- 52-Week Range: $${fundamentals.fiftyTwoWeekLow.toFixed(2)} - $${fundamentals.fiftyTwoWeekHigh.toFixed(2)}`)
    }
  }

  parts.push(
    '',
    'Provide your analysis in the specified JSON format. Be balanced and educational.',
  )

  return parts.join('\n')
}

/**
 * Parse Claude's response into structured analysis
 */
function parseAnalysisResponse(
  content: string,
  ticker: string,
  inputTokens: number,
  outputTokens: number
): StockAnalysis {
  // Try to extract JSON from the response
  let jsonStr = content

  // Handle markdown code blocks
  const jsonMatch = content.match(/```(?:json)?\s*([\s\S]*?)```/)
  if (jsonMatch) {
    jsonStr = jsonMatch[1].trim()
  }

  try {
    const parsed = JSON.parse(jsonStr)

    return {
      ticker,
      timestamp: new Date().toISOString(),
      dataFreshness: new Date().toISOString(),
      confidenceLevel: parsed.confidenceLevel || 3,
      investmentThesis: parsed.investmentThesis || 'Analysis unavailable',
      bullishFactors: parsed.bullishFactors || [],
      bearishFactors: parsed.bearishFactors || [],
      technicalSetup: parsed.technicalSetup || 'Technical analysis unavailable',
      catalysts: parsed.catalysts || [],
      bottomLine: parsed.bottomLine || 'No conclusion available',
      disclaimer: 'This is AI-generated analysis for educational purposes only. Not financial advice. Always do your own research and consult a financial advisor before making investment decisions.',
      inputTokens,
      outputTokens,
      estimatedCost: calculateCost(inputTokens, outputTokens),
    }
  } catch {
    // If JSON parsing fails, create a basic response
    console.error('Failed to parse Claude response as JSON:', content.substring(0, 200))

    return {
      ticker,
      timestamp: new Date().toISOString(),
      dataFreshness: new Date().toISOString(),
      confidenceLevel: 2,
      investmentThesis: content.substring(0, 500),
      bullishFactors: ['Unable to parse structured analysis'],
      bearishFactors: ['Unable to parse structured analysis'],
      technicalSetup: 'See raw analysis above',
      catalysts: [],
      bottomLine: 'Analysis parsing failed - see thesis for raw response',
      disclaimer: 'This is AI-generated analysis for educational purposes only. Not financial advice.',
      inputTokens,
      outputTokens,
      estimatedCost: calculateCost(inputTokens, outputTokens),
    }
  }
}

/**
 * Analyze a stock using Claude
 */
export async function analyzeStock(
  ticker: string,
  quote: Quote,
  fundamentals: Fundamentals | null
): Promise<StockAnalysis> {
  const client = getClient()

  const systemPrompt = getSystemPrompt()
  const userPrompt = buildUserPrompt(ticker, quote, fundamentals)

  try {
    const response = await client.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 1024,
      system: systemPrompt,
      messages: [
        {
          role: 'user',
          content: userPrompt,
        },
      ],
    })

    const content = response.content[0]
    if (content.type !== 'text') {
      throw new Error('Unexpected response type from Claude')
    }

    const analysis = parseAnalysisResponse(
      content.text,
      ticker,
      response.usage.input_tokens,
      response.usage.output_tokens
    )

    // Log cost for debugging
    console.log(`Claude analysis for ${ticker}: ${response.usage.input_tokens} input, ${response.usage.output_tokens} output, ~$${analysis.estimatedCost.toFixed(4)}`)

    return analysis
  } catch (error) {
    console.error('Claude API error:', error)

    if (error instanceof Anthropic.APIError) {
      if (error.status === 401) {
        throw new Error('Invalid Anthropic API key. Please check your ANTHROPIC_API_KEY.')
      }
      if (error.status === 429) {
        throw new Error('Rate limit exceeded. Please wait a moment and try again.')
      }
      throw new Error(`Claude API error: ${error.message}`)
    }

    throw error
  }
}
