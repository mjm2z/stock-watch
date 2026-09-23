/** Server-only capability checks; credentials never reach the client. */
export function aiAnalysisEnabled(): boolean {
  return process.env.STOCK_WATCH_ENABLE_AI_ANALYSIS === 'true'
    && Boolean(process.env.ANTHROPIC_API_KEY)
    && Boolean(process.env.FINNHUB_API_KEY)
}
