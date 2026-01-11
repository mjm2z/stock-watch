# AI Stock Analysis Dashboard - Claude Prompts by Phase

This document contains sequential Claude prompts to build the AI Stock Analysis Dashboard as specified in `stock-dashboard-architecture.md`. Each prompt builds upon the previous one and should be executed in order.

---

## Prompt 0: Project Initialization & Setup

**Expected Outcome:** A fully configured Next.js 14 project with all dependencies, project structure, TypeScript configuration, and environment setup ready for feature development.

### Prompt:

```
Initialize a Next.js 14 project for an AI-powered stock analysis dashboard with the following specifications:

**Project Setup:**
- Create a new Next.js 14 project with App Router
- Configure TypeScript 5.x with strict mode
- Set up Tailwind CSS 3.x with a clean, professional theme
- Install and configure shadcn/ui component library
- Install Jotai 2.x for state management
- Install lightweight-charts (TradingView) for stock charts

**Project Structure:**
Create the following directory structure:
- /app (Next.js app directory with API routes)
- /app/api (API routes)
- /app/stock/[ticker] (Dynamic stock detail pages)
- /components (React components)
- /components/ui (shadcn/ui components)
- /lib (Utilities & helpers)
- /types (TypeScript type definitions)
- /tests (Jest test files)

**Configuration Files:**
- Create .env.example with placeholders for FMP_API_KEY and ANTHROPIC_API_KEY
- Configure Jest with React Testing Library
- Set up ESLint and Prettier

**Base Types (in /types/index.ts):**
Create TypeScript interfaces for:
- Stock (ticker, name, price, change, marketCap, sector, exchange)
- Quote (current price, open, high, low, volume, change percentage)
- Fundamentals (P/E ratio, EPS, revenue, market cap, etc.)
- PaperTrade (id, type, ticker, entryDate, entryPrice, currentPrice, shares, investment, profitLoss, status, etc.)

**Data Provider Abstraction (in /lib/market-data.ts):**
Create a MarketDataProvider interface with methods:
- searchStocks(query: string): Promise<Stock[]>
- getQuote(ticker: string): Promise<Quote>
- getFundamentals(ticker: string): Promise<Fundamentals>
- getHistoricalPrices(ticker: string, range: string): Promise<PriceData[]>

**Initial Jotai Atoms (in /lib/atoms.ts):**
- watchlistAtom (persisted to localStorage)
- paperTradesAtom (persisted to localStorage)
- Create a derived portfolioValueAtom

**Scripts in package.json:**
- dev, build, start, lint, test, test:coverage, type-check

Do not implement any features yet - just set up the foundation.
```

### Checklist:
- [ ] Next.js 14 project created with App Router
- [ ] TypeScript configured with strict mode
- [ ] Tailwind CSS and shadcn/ui installed
- [ ] Jotai and lightweight-charts installed
- [ ] Project structure created
- [ ] Base types defined
- [ ] MarketDataProvider interface created
- [ ] Jotai atoms initialized with localStorage persistence
- [ ] Jest configured
- [ ] Environment variables template created

---

## Phase 1A: Core MVP (Prompts 1-5)

---

## Prompt 1: Quality Stock Search

**Expected Outcome:** A search component with autocomplete that filters stocks by quality criteria and displays results with key metrics.

### Prompt:

```
Building on the existing project, implement the Quality Stock Search feature:

**FMP API Integration (/lib/fmp.ts):**
- Implement the MarketDataProvider interface for FMP API
- Create a searchStocks function that queries FMP's search endpoint
- Implement server-side rate limiting (track calls, max 250/day for free tier)
- Add 5-minute cache for search results

**Quality Filters (apply automatically to all search results):**
- Market Cap >= $500M
- Stock Price >= $5
- Daily Volume >= 500K
- Exchanges: NYSE, NASDAQ, AMEX only
- Exclude OTC/pink sheets

**API Route (/app/api/stock/search/route.ts):**
- GET endpoint accepting ?query= parameter
- Apply quality filters server-side
- Return filtered results with: ticker, name, price, 1D % change, marketCap, sector
- Cache results for 5 minutes

**Search Component (/components/StockSearch.tsx):**
- Search input with debounced autocomplete (300ms delay)
- Display results in a dropdown list showing:
  - Ticker (bold), Company Name
  - Current Price, 1D % change (color-coded: green positive, red negative)
  - Market Cap, Sector
- Click result to navigate to /stock/[ticker]
- Handle loading and error states gracefully
- Mobile-responsive design

**Homepage Integration (/app/page.tsx):**
- Center the search bar prominently
- Add a brief tagline: "AI-Powered Stock Research"
- Clean, minimal design

Ensure the search works end-to-end with the FMP API. Handle API errors gracefully with user-friendly messages.
```

### Checklist:
- [ ] FMP API client implemented with rate limiting
- [ ] Quality filters applied to search results
- [ ] Search API route created with caching
- [ ] Search component with debounced autocomplete
- [ ] Results display ticker, price, change, market cap, sector
- [ ] Color-coded price changes (green/red)
- [ ] Navigation to stock detail page on click
- [ ] Error handling and loading states
- [ ] Mobile-responsive design

---

## Prompt 2: TradingView Charts

**Expected Outcome:** Interactive candlestick charts with timeframe selection and technical indicators on the stock detail page.

### Prompt:

```
Building on the existing project, implement TradingView Lightweight Charts:

**Historical Data API (/app/api/stock/[ticker]/history/route.ts):**
- GET endpoint accepting ?range= parameter (1D, 1W, 1M, 3M, 1Y, 5Y)
- Fetch historical OHLCV data from FMP API
- Cache strategy: 15 minutes for intraday, 24 hours for daily+
- Return data formatted for TradingView charts

**Chart Component (/components/StockChart.tsx):**
- Use TradingView lightweight-charts library
- Default view: Candlestick chart
- Timeframe selector buttons: 1D, 1W, 1M, 3M, 1Y, 5Y
- Technical indicators:
  - 50-day moving average (blue line)
  - 200-day moving average (orange line)
  - Volume bars at bottom
  - RSI indicator (optional toggle, separate pane)
- Responsive design: adapts to container width
- Dark/light theme support based on system preference
- Loading skeleton while data fetches

**Stock Detail Page (/app/stock/[ticker]/page.tsx):**
- Display stock name and ticker prominently
- Show current price with real-time styling (up/down indicator)
- Embed the StockChart component
- Add placeholder sections for:
  - AI Analysis (to be implemented in Prompt 3)
  - Key Metrics sidebar
- Fetch and display basic quote data (price, change, volume, market cap)

**Performance Requirements:**
- Chart should render in <2 seconds
- Smooth transitions when changing timeframes
- No layout shift during loading

Ensure charts work correctly with real FMP data across all timeframes.
```

### Checklist:
- [ ] Historical data API route with caching
- [ ] Candlestick chart rendering
- [ ] Timeframe selector (1D, 1W, 1M, 3M, 1Y, 5Y)
- [ ] 50-day and 200-day moving averages
- [ ] Volume bars displayed
- [ ] RSI toggle (optional indicator)
- [ ] Responsive chart sizing
- [ ] Stock detail page layout created
- [ ] Current price and change displayed
- [ ] Loading states and skeletons

---

## Prompt 3: One-Click AI Analysis

**Expected Outcome:** Claude-powered stock analysis with investment thesis, cached results, and cost-optimized API calls.

### Prompt:

```
Building on the existing project, implement One-Click AI Analysis with Claude:

**Claude API Client (/lib/claude.ts):**
- Create Anthropic client using ANTHROPIC_API_KEY
- Implement prompt caching strategy:
  - Cache system prompt + market context (reusable across analyses)
  - Only send ticker-specific data as variable input
- Track token usage for cost monitoring
- Handle API errors gracefully with retries (max 3)

**Analysis Cache (/lib/cache.ts):**
- Implement analysis caching with 6-hour TTL
- Smart re-analysis triggers:
  - Last analysis > 6 hours old
  - Price moved > 5% since last analysis
  - Macro trigger detected (VIX spike, etc.)
- Store in memory or localStorage for Phase 1

**Analysis API Route (/app/api/analyze/route.ts):**
- POST endpoint accepting { ticker, forceRefresh? }
- Check cache first, return cached if valid
- Fetch fresh data from FMP: quote, fundamentals, recent news
- Send to Claude with structured prompt
- Return analysis with metadata (timestamp, data freshness, cost)

**Claude Prompt Structure:**
The prompt should request:
- Investment thesis (2-minute read summary)
- Probabilistic assessment with confidence level (1-5 scale)
- Bullish factors (3-5 points)
- Bear case (always include, 3-5 points)
- Technical setup (current trend, key levels)
- Catalysts (upcoming events, earnings, etc.)
- Bottom line recommendation (with "lean" language, not absolutes)
- Always include disclaimer about AI limitations

**Analysis Display Component (/components/StockAnalysis.tsx):**
- "Analyze" button on stock detail page
- Loading state with estimated wait time
- Display formatted analysis with clear sections
- Show data freshness timestamp
- Show confidence level with visual indicator
- Action buttons: "Add to Watchlist", "Paper Trade"
- "Re-analyze" button (bypasses cache)

**Cost Tracking:**
- Log each API call cost to console
- Store running total in localStorage
- Display cost per analysis in UI (e.g., "~$0.04")

**Integration on Stock Page:**
- Add the Analyze button and display area to /app/stock/[ticker]/page.tsx
- Position below the chart

Ensure analysis provides balanced, useful insights with clear disclaimers about AI limitations.
```

### Checklist:
- [ ] Claude API client with prompt caching
- [ ] Token usage tracking
- [ ] Analysis caching with 6-hour TTL
- [ ] Smart re-analysis triggers implemented
- [ ] Analysis API route created
- [ ] Structured prompt returns balanced analysis
- [ ] Analysis display component with sections
- [ ] Data freshness timestamp shown
- [ ] Confidence level indicator
- [ ] Action buttons (Watchlist, Paper Trade)
- [ ] Cost per analysis displayed
- [ ] Disclaimer included in every analysis

---

## Prompt 4: Personal Watchlist

**Expected Outcome:** A watchlist feature to track favorite stocks with real-time prices, sorting, and quick actions.

### Prompt:

```
Building on the existing project, implement the Personal Watchlist feature:

**Watchlist State (update /lib/atoms.ts):**
- Ensure watchlistAtom uses atomWithStorage for localStorage persistence
- Type: Array of { ticker, addedAt, notes?, lastAnalyzed? }
- Add derived atom for watchlist with current prices

**Watchlist API Route (/app/api/watchlist/prices/route.ts):**
- GET endpoint to batch-fetch current prices for all watchlist tickers
- Single FMP API call for efficiency (batch quote endpoint)
- Cache for 2 minutes
- Return array of { ticker, price, change, changePercent }

**Watchlist Component (/components/Watchlist.tsx):**
- Sortable table with columns:
  - Ticker (clickable, navigates to stock page)
  - Current Price
  - 1D % Change (color-coded green/red)
  - Your Notes (editable inline)
  - Last Analyzed (timestamp or "Never")
- Sort by: Ticker, Price, Change %, Date Added
- Quick action buttons per row:
  - Re-analyze (triggers analysis)
  - View Chart (navigates to stock page)
  - Add Paper Trade (opens modal)
  - Remove from watchlist (with confirmation)
- Empty state: "Add stocks to your watchlist to track them"

**Add to Watchlist Flow:**
- Button on stock detail page and in search results
- If already in watchlist, show "In Watchlist" badge instead
- Optional: Add notes when adding

**Watchlist Page (/app/watchlist/page.tsx):**
- Display the Watchlist component
- Show total count: "Tracking X stocks"
- Add search/filter within watchlist
- Refresh button to update all prices

**Export/Import (basic, expanded in Phase 1B):**
- "Export" button: Download watchlist as JSON
- Prepare for import functionality

**Data Resilience:**
- Handle localStorage being cleared gracefully
- Show warning if localStorage is getting full (approaching 5MB)

**Pro Tip Display:**
- Show tip: "Start with 10-20 stocks. Master these before expanding."
- Dismiss-able, stored in localStorage

Ensure watchlist persists across browser sessions and handles edge cases.
```

### Checklist:
- [ ] Watchlist atom with localStorage persistence
- [ ] Batch price fetching API route
- [ ] Sortable watchlist table
- [ ] Column: Ticker, Price, Change, Notes, Last Analyzed
- [ ] Quick actions: Re-analyze, View, Paper Trade, Remove
- [ ] Add to watchlist from stock page and search
- [ ] Watchlist page created
- [ ] Export to JSON functionality
- [ ] Empty state handling
- [ ] Storage warning for localStorage limits

---

## Prompt 5: Paper Trading (Basic)

**Expected Outcome:** Create and track hypothetical trades to validate AI recommendations, with performance metrics.

### Prompt:

```
Building on the existing project, implement Basic Paper Trading:

**Paper Trade Types (update /types/index.ts):**
```typescript
interface PaperTrade {
  id: string;
  type: 'paper' | 'real';
  ticker: string;
  entryDate: string;
  entryPrice: number;
  currentPrice: number;
  shares: number;
  investment: number;
  profitLoss: number;
  profitLossPct: number;
  holdPeriod: '1_week' | '1_month' | '3_months' | '6_months' | '1_year';
  targetPrice?: number;
  notes?: string;
  status: 'active' | 'closed';
  // Audit trail (for Phase 1B expansion)
  claudePrompt?: string;
  claudeResponse?: string;
  analysisTimestamp?: string;
}
```

**Paper Trades State (update /lib/atoms.ts):**
- paperTradesAtom with localStorage persistence
- Derived atoms:
  - activeTrades (filter by status === 'active')
  - portfolioValue (sum of currentPrice * shares)
  - totalProfitLoss
  - winRate (completed trades with positive P&L)

**Create Trade Modal (/components/CreateTradeModal.tsx):**
- Trade type selector (required): Paper Trade vs Real Trade
- Visual indicators: Blue badge for paper, Green for real
- Fields:
  - Ticker (pre-filled if opened from stock page)
  - Entry Price (auto-filled with current price, editable)
  - Investment Amount (default $1,000)
  - Shares (auto-calculated from investment/price)
  - Expected Hold Period (dropdown)
  - Target Price (optional, pre-fill from Claude analysis if available)
  - Notes (optional textarea)
- Validation: All required fields, positive numbers
- Save to paperTradesAtom

**Portfolio Page (/app/portfolio/page.tsx):**
- Tab filter: All / Paper Only / Real Only
- Trade table with columns:
  - Ticker, Entry Date, Entry Price, Current Price
  - P&L ($), P&L (%), Days Held, Type (badge), Status
- Color-coded P&L (green positive, red negative)
- Click row to expand details
- Close trade button (marks as 'closed', locks P&L)

**Performance Metrics Dashboard (/components/PortfolioMetrics.tsx):**
- Display at top of portfolio page:
  - Total Trades count
  - Win Rate (%)
  - Average Gain (winners)
  - Average Loss (losers)
  - Total Invested
  - Current Value
  - Net Gain/Loss ($ and %)
- "vs. S&P 500" comparison (fetch S&P performance for same period)

**Price Update Mechanism:**
- On portfolio page load, batch-fetch current prices for all active trades
- Update currentPrice and recalculate P&L
- Cache prices for 2 minutes

**Integration:**
- "Add Paper Trade" button on stock detail page (opens modal with ticker pre-filled)
- Add Portfolio link to main navigation

Ensure trades persist and calculations are accurate. Handle edge cases like stocks with no current price data.
```

### Checklist:
- [ ] PaperTrade type with all fields
- [ ] paperTradesAtom with localStorage
- [ ] Derived atoms for portfolio calculations
- [ ] Create trade modal with type selector
- [ ] Paper vs Real visual indicators (blue/green badges)
- [ ] Auto-calculated shares from investment
- [ ] Portfolio page with trade table
- [ ] Tab filters: All, Paper, Real
- [ ] P&L calculations and color coding
- [ ] Close trade functionality
- [ ] Performance metrics dashboard
- [ ] Win rate and average gain/loss calculations
- [ ] S&P 500 comparison
- [ ] Batch price updates for active trades

---

## Phase 1B: Polish & Safety (Prompts 6-9)

---

## Prompt 6: Audit Trail

**Expected Outcome:** Store complete Claude prompts and responses with each trade for debugging and improvement.

### Prompt:

```
Building on the existing project, implement the Audit Trail feature:

**Enhanced Trade Storage:**
- When creating a paper trade after an analysis, automatically attach:
  - claudePrompt: The exact prompt sent to Claude
  - claudeResponse: The full response received
  - analysisTimestamp: When the analysis was generated
  - dataFreshness: When the market data was fetched
  - marketContext: { vix, tenYearYield, dxy, regime } at time of trade

**Update Analysis Flow (/lib/claude.ts and /app/api/analyze/route.ts):**
- Return the full prompt and response from the analyze endpoint
- Include market context snapshot in response

**Update Create Trade Modal:**
- When opened from an analysis, auto-populate audit fields
- Store silently (don't show in modal, just save with trade)

**Trade Detail View (/components/TradeDetail.tsx):**
- Expandable section: "View AI Analysis"
- Display:
  - Original analysis text
  - Data freshness timestamp
  - Market context at entry (VIX, yields, etc.)
- Collapsible by default to reduce clutter

**Analysis History Page (/app/analysis-history/page.tsx):**
- List all stored analyses (from trades + standalone)
- Columns: Ticker, Date, Confidence, Trade Created?, Outcome
- Click to view full prompt/response
- Search/filter by ticker
- Purpose: Debug bad recommendations, improve prompts over time

**Storage Considerations:**
- Audit data can be large; monitor localStorage usage
- Show warning when approaching 4MB used
- Suggest export when storage is high

This enables post-mortem analysis: "Was Claude wrong, or did the market shift?"
```

### Checklist:
- [ ] Audit fields added to trade storage
- [ ] Full prompt/response captured from analysis
- [ ] Market context snapshot included
- [ ] Trade detail view shows original analysis
- [ ] Analysis history page created
- [ ] Search/filter in analysis history
- [ ] localStorage usage monitoring
- [ ] Storage warning at 4MB threshold

---

## Prompt 7: Export/Import

**Expected Outcome:** Full data export and import for backup and migration, protecting against localStorage loss.

### Prompt:

```
Building on the existing project, implement comprehensive Export/Import:

**Export Functionality (/lib/export.ts):**
- exportAllData(): Combines watchlist, trades, analyses, settings
- exportWatchlist(): Just watchlist as JSON
- exportTrades(): Just trades as JSON
- exportAnalyses(): All stored analyses
- Format: JSON with metadata (exportDate, version, itemCount)
- Also support CSV export for trades (spreadsheet-friendly)

**Export UI (/components/ExportModal.tsx):**
- Accessed from Settings or dedicated button
- Options:
  - Export All (recommended for backup)
  - Export Watchlist Only
  - Export Trades Only
  - Export Analyses Only
- Format selector: JSON (default) or CSV (trades only)
- Download triggers browser file download

**Import Functionality (/lib/import.ts):**
- importData(file): Parse and validate imported file
- Validation:
  - Check file format and version
  - Validate required fields
  - Handle missing optional fields gracefully
- Merge strategy options:
  - Replace all (dangerous, requires confirmation)
  - Merge (add new, skip existing by ID)
  - Preview before import (show what will change)

**Import UI (/components/ImportModal.tsx):**
- File picker accepting .json files
- Preview of what will be imported:
  - "X watchlist items, Y trades, Z analyses"
  - Highlight conflicts (items that already exist)
- Merge strategy selector
- Confirm button with clear warning for Replace All

**Settings Page (/app/settings/page.tsx):**
- Create settings page if not exists
- Section: "Data Management"
  - Export buttons
  - Import button
  - Storage usage indicator (X MB of 5 MB used)
  - Clear all data button (with strong confirmation)

**Auto-Export Reminder:**
- After 50 trades or 30 days since last export, show non-intrusive reminder
- "Back up your data" notification with export button
- Dismissable, resets timer on export

Ensure import handles malformed files gracefully with clear error messages.
```

### Checklist:
- [ ] Export functions for all data types
- [ ] JSON export with metadata
- [ ] CSV export for trades
- [ ] Export modal with options
- [ ] Import with file parsing and validation
- [ ] Merge strategy options (replace, merge)
- [ ] Import preview before applying
- [ ] Settings page with data management section
- [ ] Storage usage indicator
- [ ] Clear all data with confirmation
- [ ] Auto-export reminder after 50 trades/30 days

---

## Prompt 8: Cost Tracker Widget

**Expected Outcome:** Real-time API cost monitoring to stay within budget.

### Prompt:

```
Building on the existing project, implement the Cost Tracker Widget:

**Cost Tracking State (/lib/atoms.ts):**
- apiCostsAtom with localStorage persistence:
  ```typescript
  interface ApiCosts {
    currentMonth: string; // "2024-01"
    claudeCosts: number;
    fmpCalls: number;
    analyses: number;
    budget: number; // User-configurable, default $30
    history: Array<{ month: string; total: number }>;
  }
  ```
- Reset automatically on new month

**Cost Calculation (/lib/cost-tracker.ts):**
- trackAnalysisCost(inputTokens, outputTokens): Calculate Claude cost
- Use current Claude Sonnet pricing
- Account for prompt caching (90% savings on cached portions)
- Track FMP calls count (towards 250/day limit)

**Update Claude Client:**
- After each API call, extract token counts from response
- Call trackAnalysisCost with actual usage
- Log to console for debugging

**Cost Widget Component (/components/CostWidget.tsx):**
- Small sidebar widget (or header element):
  ```
  This Month: $4.23 / $30
  85% under budget [progress bar]

  Analyses: 87 ($3.91)
  Data fetches: 142/250 today

  Next analysis: ~$0.04
  ```
- Color coding:
  - Green: < 50% of budget
  - Yellow: 50-80% of budget
  - Red: > 80% of budget
- Click to expand detailed breakdown

**Budget Alert:**
- Warning notification when reaching 80% of budget
- Hard warning at 95% (suggest reducing usage)
- Optional: Block analyses when budget exceeded (configurable)

**Settings Integration:**
- Add "API Budget" section to settings page
- Set monthly budget amount
- View historical spending by month
- Reset current month (for testing)

**FMP Rate Limit Protection:**
- Track daily FMP calls
- Warning at 200 calls (80% of 250 limit)
- Reduce refresh frequency when approaching limit
- Reset counter at midnight

Keep the widget minimal and non-intrusive while providing essential visibility.
```

### Checklist:
- [ ] ApiCosts state with localStorage
- [ ] Automatic monthly reset
- [ ] Cost calculation from token usage
- [ ] Prompt caching savings accounted for
- [ ] FMP call tracking
- [ ] Cost widget component
- [ ] Progress bar with color coding
- [ ] Budget warnings at 80% and 95%
- [ ] Settings page budget configuration
- [ ] Historical spending view
- [ ] FMP rate limit protection
- [ ] Daily FMP counter reset

---

## Prompt 9: Market Context Widget

**Expected Outcome:** Display key market indicators (VIX, yields, DXY, Fear & Greed) that influence analysis.

### Prompt:

```
Building on the existing project, implement the Market Context Widget:

**Market Context API (/app/api/market-context/route.ts):**
- Fetch key indicators:
  - VIX (volatility index)
  - 10-Year Treasury Yield
  - DXY (US Dollar Index)
  - S&P 500 current level and daily change
- Cache for 15 minutes
- Use FMP or alternative free data sources
- Calculate market regime: 'risk-on', 'risk-off', 'neutral'

**Market Regime Logic:**
- Risk-On: VIX < 20, yields stable, DXY falling
- Risk-Off: VIX > 25, yields spiking, DXY rising
- Neutral: Mixed signals

**Market Context Component (/components/MarketContext.tsx):**
- Compact display (sidebar or header):
  ```
  MARKET CONTEXT
  VIX: 16.2 (Low)
  10Y Yield: 4.2%
  DXY: 102.5
  S&P 500: 5,200 (+0.8%)
  Regime: Risk-On
  ```
- Color coding:
  - VIX: Green < 20, Yellow 20-25, Red > 25
  - Regime badge with appropriate color
- Tooltip explanations for each indicator
- Last updated timestamp

**Integration with Analysis:**
- Pass market context to Claude analysis prompt
- Include regime in analysis context
- Market context shown in analysis output

**Macro Trigger Detection:**
- Define significant moves:
  - VIX change > 3 points in a day
  - Yield change > 0.1% in a day
  - DXY change > 1% in a day
- When triggered, invalidate analysis cache for affected stocks
- Show alert: "Market conditions changed significantly"

**Dashboard Integration:**
- Add MarketContext widget to:
  - Homepage (below search)
  - Stock detail page (sidebar)
- Refresh button to force update

This provides critical context for all stock analyses.
```

### Checklist:
- [ ] Market context API route
- [ ] Fetch VIX, yields, DXY, S&P 500
- [ ] 15-minute cache
- [ ] Market regime calculation
- [ ] Compact widget display
- [ ] Color-coded indicators
- [ ] Tooltip explanations
- [ ] Last updated timestamp
- [ ] Integration with Claude analysis prompt
- [ ] Macro trigger detection
- [ ] Cache invalidation on significant moves
- [ ] Widget on homepage and stock detail page

---

## Phase 2: High-Value Enhancements (Prompts 10-14)

---

## Prompt 10: "Why Did This Move?" Auto-Analysis

**Expected Outcome:** Automatic analysis when watchlist stocks make significant moves, explaining the reason.

### Prompt:

```
Building on the existing project, implement "Why Did This Move?" Auto-Analysis:

**Movement Detection (/lib/movement-detector.ts):**
- Check watchlist stocks for significant moves:
  - Daily change >= 5% (up or down)
  - Pre-market/after-hours moves >= 3%
- Run check on app load and every 30 minutes when app is open
- Track which moves have been analyzed to avoid duplicates

**Move Analysis API (/app/api/analyze/move/route.ts):**
- POST endpoint accepting { ticker, movePercent, direction }
- Fetch relevant context:
  - Recent news (last 24 hours)
  - Earnings reports
  - Analyst actions
  - SEC filings
- Send to Claude with move-specific prompt

**Claude Prompt for Moves:**
- Request explanation format:
  ```
  [TICKER] [+/-X%] (Pre-market/Today)

  WHY: [Primary reason - 1 line]
  • [Supporting detail 1]
  • [Supporting detail 2]
  • [Supporting detail 3]

  MARKET REACTION:
  • [Options activity if notable]
  • [Analyst actions if any]

  WHAT TO DO:
  [Brief recommendation based on move type and user's position]

  Analyzed at [time]
  ```

**Move Alerts Component (/components/MoveAlerts.tsx):**
- Display panel showing recent significant moves
- Each alert shows:
  - Ticker with move percentage (color-coded)
  - Brief "why" explanation
  - Timestamp
  - "Full Analysis" button
- Dismissable alerts
- Badge count on icon when new moves detected

**Notification System:**
- Visual indicator (badge/dot) when new moves detected
- Optional: Browser notification permission request
- Alert sound toggle in settings

**Move History (/app/moves/page.tsx):**
- Historical list of all detected moves
- Filter by: date range, direction (up/down), magnitude
- Useful for pattern recognition over time

**Integration:**
- Move alerts visible on dashboard/homepage
- Link from move alert to full stock analysis
- Auto-suggest adding paper trade after move analysis

**Cost Management:**
- Batch non-urgent move analyses (queue for next batch)
- Limit to 10 auto-analyses per day
- User can trigger manual analysis beyond limit

Expected cost: ~$0.05-0.10 per move analysis, ~$2-3/month for typical usage.
```

### Checklist:
- [ ] Movement detection for watchlist stocks
- [ ] 5% daily / 3% pre-market thresholds
- [ ] Duplicate move tracking
- [ ] Move analysis API endpoint
- [ ] News and context fetching
- [ ] Claude prompt for move explanations
- [ ] Move alerts component
- [ ] Dismissable alerts with timestamps
- [ ] Badge count for new moves
- [ ] Optional browser notifications
- [ ] Move history page with filters
- [ ] Daily auto-analysis limit (10)
- [ ] Cost tracking for move analyses

---

## Prompt 11: Second Opinion / Devil's Advocate Mode

**Expected Outcome:** AI-powered counter-analysis that challenges trade ideas and identifies risks.

### Prompt:

```
Building on the existing project, implement Second Opinion / Devil's Advocate Mode:

**Second Opinion API (/app/api/second-opinion/route.ts):**
- POST endpoint accepting { ticker, userThesis, tradeDirection }
- Fetch current data (quote, fundamentals, recent analyses)
- Send to Claude with devil's advocate prompt

**Devil's Advocate Prompt:**
- Instruct Claude to argue AGAINST the user's thesis
- Request structure:
  ```
  THE CASE AGAINST [TICKER] @ $[PRICE]

  Why this could go wrong:
  1. [Risk factor with data]
  2. [Risk factor with data]
  3. [Risk factor with data]

  PERSONAL EDGE SCORING: [X/10]
  [Analysis based on user's historical patterns if available]
  ✓/✗ [Pattern matches/mismatches]

  RECOMMENDED NEXT STEPS:
  1. [Option 1 with explanation]
  2. [Option 2 with explanation]
  3. [Option 3 with explanation]
  ```

**Confidence Scoring:**
- Color-coded output:
  - Red (1-3): HIGH RISK - Strong case against
  - Yellow (4-6): MEDIUM RISK - Mixed signals
  - Green (7-10): LOW RISK - Thesis holds up well
- Include historical accuracy disclaimer

**Personal Pattern Analysis (if 20+ trades exist):**
- Compare current setup to user's historical trades
- Identify pattern matches (e.g., "large-cap tech" = your strength)
- Identify pattern mismatches (e.g., "momentum chasing" = your weakness)
- Reference specific past trades as examples

**Second Opinion Modal (/components/SecondOpinionModal.tsx):**
- Trigger: "Get Second Opinion" button before any trade
- Input fields:
  - Ticker (pre-filled)
  - Your thesis (text area)
  - Trade direction (Buy/Sell)
  - Confidence level (1-10 slider)
- Display devil's advocate response
- Color-coded based on risk level
- Clear action recommendations

**Integration Points:**
- Add button on stock detail page
- Add button in Create Trade modal ("Check First")
- Prompt before confirming trades over $500 (optional)

**Historical Tracking:**
- Store second opinion responses
- After trade closes, compare outcome to warnings
- Build accuracy metrics: "Second opinion correctly warned: 72%"

This is the most valuable Phase 2 feature - prevents emotional/impulsive trades.
```

### Checklist:
- [ ] Second opinion API endpoint
- [ ] Devil's advocate prompt structure
- [ ] Risk factors analysis
- [ ] Color-coded confidence scoring
- [ ] Personal pattern analysis (if 20+ trades)
- [ ] Historical trade comparison
- [ ] Second opinion modal component
- [ ] Thesis input with trade direction
- [ ] Action recommendations
- [ ] Integration on stock page and trade modal
- [ ] Optional prompt for trades > $500
- [ ] Historical tracking of second opinions
- [ ] Accuracy metrics for warnings

---

## Prompt 12: Learning Mode / Pattern Recognition

**Expected Outcome:** AI analysis of user's trading patterns to identify strengths and weaknesses.

### Prompt:

```
Building on the existing project, implement Learning Mode / Pattern Recognition:

**Pattern Analysis API (/app/api/patterns/route.ts):**
- POST endpoint (no input needed, analyzes all trades)
- Requires minimum 20 completed trades
- Aggregate trade data:
  - Win/loss by sector
  - Win/loss by market cap
  - Win/loss by hold period
  - Win/loss by entry type (pullback, breakout, momentum)
  - Performance by market regime
- Send aggregated data to Claude for pattern analysis

**Claude Pattern Prompt:**
- Request comprehensive analysis:
  ```
  YOUR TRADING PATTERNS ([X] trades analyzed)

  YOU'RE BEST AT:
  1. [Pattern] ([win rate]% win rate)
  2. [Pattern] ([win rate]% win rate)
  3. [Pattern] ([win rate]% win rate)

  YOU STRUGGLE WITH:
  1. [Pattern] ([win rate]% win rate) - [recommendation]
  2. [Pattern] ([win rate]% win rate) - [recommendation]

  PERSONAL EDGE SCORING FACTORS:
  [List of factors that predict success for this user]

  HUMILITY CHECK - Claude's False Positives:
  [List trades where Claude was confident but wrong]
  Win rate on "high confidence" calls: [X]%
  ```

**Pattern Dashboard (/components/PatternDashboard.tsx):**
- Visual display of trading patterns
- Charts:
  - Win rate by sector (bar chart)
  - Win rate by hold period (bar chart)
  - P&L by market regime (grouped bars)
- Strengths section with green highlighting
- Weaknesses section with red highlighting
- Specific trade examples for each pattern

**Personal Edge Score Integration:**
- When analyzing a new stock, calculate "Personal Edge Score"
- Based on how many strength patterns the setup matches
- Display: "This setup matches 3 of your strength patterns"
- Warning: "This setup triggers 2 of your weakness patterns"

**Learning Page (/app/learning/page.tsx):**
- Full pattern analysis display
- Historical performance charts
- Claude's track record section:
  - Total recommendations
  - Accuracy by confidence level
  - False positive examples
- "What I've learned" summary
- Refresh analysis button (monthly recommended)

**Notifications:**
- When creating a trade that matches weakness pattern: "Heads up: Small-caps have a 32% win rate for you"
- When setup matches strength: "This matches your best setups"

**Minimum Data Requirements:**
- Show "Need X more trades" message if < 20 trades
- Partial analysis available at 10 trades
- Full analysis unlocked at 20+ trades

This creates personalized, actionable insights unique to each user.
```

### Checklist:
- [ ] Pattern analysis API endpoint
- [ ] Trade aggregation by sector, market cap, hold period
- [ ] Claude pattern analysis prompt
- [ ] Strengths and weaknesses identification
- [ ] Humility check section (Claude's failures)
- [ ] Pattern dashboard component
- [ ] Win rate charts by category
- [ ] Personal Edge Score calculation
- [ ] Learning page with full analysis
- [ ] Claude track record section
- [ ] Trade creation warnings for weakness patterns
- [ ] Minimum trade requirements (10 partial, 20 full)

---

## Prompt 13: Smart Alerts & Notifications

**Expected Outcome:** Configurable alerts for price targets, technical signals, and events.

### Prompt:

```
Building on the existing project, implement Smart Alerts & Notifications:

**Alert Types & Data Model (/types/index.ts):**
```typescript
interface Alert {
  id: string;
  ticker: string;
  type: 'price' | 'technical' | 'event' | 'volume';
  condition: {
    // Price alerts
    targetPrice?: number;
    direction?: 'above' | 'below';
    // Technical alerts
    indicator?: 'ma50' | 'ma200' | 'rsi' | 'golden_cross' | 'death_cross';
    // Volume alerts
    volumeMultiple?: number; // e.g., 2.0 = 2x average
    // Event alerts
    eventType?: 'earnings' | 'dividend' | 'split';
  };
  createdAt: string;
  triggeredAt?: string;
  status: 'active' | 'triggered' | 'dismissed';
  notificationSent: boolean;
}
```

**Alert Checking Service (/lib/alert-checker.ts):**
- Check all active alerts on app load and every 15 minutes
- Price alerts: Compare current price to target
- Technical alerts:
  - MA crossovers (price crosses above/below 50-day or 200-day MA)
  - RSI thresholds (overbought > 70, oversold < 30)
  - Golden cross (50-day crosses above 200-day)
  - Death cross (50-day crosses below 200-day)
- Volume alerts: Compare current volume to average
- Event alerts: Check upcoming earnings/events calendar

**Alerts API Routes:**
- GET /api/alerts - List all alerts
- POST /api/alerts - Create new alert
- DELETE /api/alerts/[id] - Remove alert
- POST /api/alerts/check - Manually trigger check

**Create Alert Modal (/components/CreateAlertModal.tsx):**
- Ticker input (with autocomplete)
- Alert type selector
- Condition fields (dynamic based on type):
  - Price: Target price, direction (above/below)
  - Technical: Indicator dropdown
  - Volume: Multiple threshold (1.5x, 2x, 3x)
  - Event: Event type dropdown
- Preview: "Alert when AAPL goes above $185"

**Alerts List Component (/components/AlertsList.tsx):**
- Display all alerts grouped by status (Active, Triggered, Dismissed)
- Each alert shows:
  - Ticker and condition
  - Current status
  - Created date
  - Triggered date (if applicable)
- Actions: Edit, Delete, Snooze

**Notification Display:**
- In-app notification bell with badge count
- Toast notifications when alerts trigger
- Notification center panel showing recent alerts
- Optional browser notifications (request permission)

**Alerts Page (/app/alerts/page.tsx):**
- Full alerts management
- Create new alert button
- Filter by status, type, ticker
- Bulk actions (dismiss all triggered, delete all)

**Quick Alert Creation:**
- On stock page: "Alert me when..." quick buttons
- Common alerts: +5% from here, -5% from here, hits 52-week high/low

**Batch Processing:**
- Use Batch API for overnight alert checking (50% cost savings)
- Real-time checking only during market hours

Expected cost: ~$1-2/month for alert monitoring.
```

### Checklist:
- [ ] Alert data model with all types
- [ ] Alert checking service
- [ ] Price alert logic
- [ ] Technical alert logic (MA, RSI, crosses)
- [ ] Volume alert logic
- [ ] Event alert logic
- [ ] Alerts API routes (CRUD)
- [ ] Create alert modal with dynamic fields
- [ ] Alerts list component
- [ ] Notification bell with badge
- [ ] Toast notifications on trigger
- [ ] Optional browser notifications
- [ ] Alerts management page
- [ ] Quick alert buttons on stock page
- [ ] Batch processing for overnight checks

---

## Prompt 14: Trade Journal Integration

**Expected Outcome:** Comprehensive trade journaling with notes, emotions, and post-trade review.

### Prompt:

```
Building on the existing project, implement Trade Journal Integration:

**Enhanced Trade Data Model (update /types/index.ts):**
```typescript
interface TradeJournalEntry {
  tradeId: string;  // Links to PaperTrade
  // Pre-trade
  preTradeThesis: string;
  preTradeConfidence: number; // 1-10
  preTradeEmotions: ('confident' | 'anxious' | 'fomo' | 'patient' | 'impulsive')[];
  preTradeChecklist: {
    reviewedAnalysis: boolean;
    gotSecondOpinion: boolean;
    sizeAppropriate: boolean;
    hasExitPlan: boolean;
  };
  // During trade
  holdingNotes: Array<{ date: string; note: string }>;
  // Post-trade (filled when closed)
  postTradeReview?: {
    whatWentWell: string;
    whatWentWrong: string;
    lessonsLearned: string;
    wouldTakeAgain: boolean;
    actualVsExpected: 'better' | 'worse' | 'as_expected';
  };
}
```

**Pre-Trade Journal Modal (/components/PreTradeJournal.tsx):**
- Appears before confirming any trade
- Required fields:
  - Thesis (why are you taking this trade?)
  - Confidence level (1-10 slider)
  - Emotional state (multi-select)
- Pre-trade checklist (checkboxes):
  - [ ] Reviewed AI analysis
  - [ ] Got second opinion
  - [ ] Position size appropriate
  - [ ] Have exit plan (stop loss, target)
- All required for trade submission
- Purpose: Force intentional trading, reduce impulsive decisions

**Holding Notes (/components/HoldingNotes.tsx):**
- On trade detail page
- "Add Note" button
- Log thoughts during the trade:
  - Date auto-filled
  - Free-form text
  - Optional emotion tag
- See all notes chronologically

**Post-Trade Review Modal (/components/PostTradeReview.tsx):**
- Triggered when closing a trade
- Required fields:
  - What went well?
  - What went wrong?
  - Key lessons learned
  - Would you take this trade again? (Yes/No)
  - Outcome vs expectations (Better/Worse/As expected)
- Compare actual P&L to original thesis
- Show original pre-trade journal for reference

**Journal Page (/app/journal/page.tsx):**
- Timeline view of all journal entries
- Filter by: date range, emotion, outcome
- Search within notes
- Export journal to PDF/Markdown

**Journal Insights (/components/JournalInsights.tsx):**
- Aggregate analysis:
  - Win rate by emotional state
  - Win rate by confidence level
  - Most common lessons
- "You perform best when feeling: [patient, confident]"
- "You perform worst when feeling: [fomo, impulsive]"
- Correlate checklist completion with outcomes

**Integration:**
- Journal icon on trade row to access entries
- "Journal" link in main navigation
- Prompt for post-trade review when closing
- Badge if review not completed

**Quotes & Motivation:**
- Rotating trading wisdom quotes on journal page
- "The goal of a successful trader is to make the best trades. Money is secondary." - Alexander Elder

This creates accountability and accelerates learning from experience.
```

### Checklist:
- [ ] TradeJournalEntry data model
- [ ] Pre-trade journal modal
- [ ] Thesis, confidence, emotions required
- [ ] Pre-trade checklist
- [ ] Holding notes component
- [ ] Chronological notes display
- [ ] Post-trade review modal
- [ ] Required fields on trade close
- [ ] Compare outcome to original thesis
- [ ] Journal page with timeline
- [ ] Filter and search in journal
- [ ] Export to PDF/Markdown
- [ ] Journal insights with correlations
- [ ] Emotion-to-outcome analysis
- [ ] Checklist-to-outcome correlation

---

## Final Integration & Polish (Optional Prompt 15)

**Expected Outcome:** Final polish, performance optimization, and deployment readiness.

### Prompt:

```
Perform final integration and polish for the AI Stock Analysis Dashboard:

**Navigation & Layout:**
- Ensure consistent navigation across all pages:
  - Home (Search)
  - Watchlist
  - Portfolio
  - Alerts
  - Journal
  - Learning
  - Settings
- Mobile-responsive navigation (hamburger menu)
- Consistent header with market context widget

**Performance Optimization:**
- Implement React.lazy for route-based code splitting
- Optimize bundle size (analyze with webpack-bundle-analyzer)
- Ensure all images are optimized
- Add loading skeletons for all async content
- Target: < 2 second initial load

**Error Handling:**
- Global error boundary
- Graceful degradation when APIs fail
- User-friendly error messages
- Retry buttons for failed requests
- Offline indicator

**Accessibility:**
- Keyboard navigation support
- ARIA labels on interactive elements
- Color contrast compliance
- Screen reader testing

**Testing:**
- Unit tests for utility functions
- Component tests for key UI elements
- Integration tests for API routes
- Aim for 70%+ code coverage

**Documentation:**
- README with setup instructions
- Environment variables documentation
- API routes documentation
- Component storybook (optional)

**Final Checklist:**
- [ ] All Phase 1A features working
- [ ] All Phase 1B features working
- [ ] All Phase 2 features working
- [ ] Mobile responsive
- [ ] Error handling complete
- [ ] Performance targets met
- [ ] Tests passing
- [ ] Documentation complete

The app should now be a fully functional, personal AI stock research assistant.
```

---

## Summary

| Phase | Prompts | Features |
|-------|---------|----------|
| **Setup** | 0 | Project initialization |
| **Phase 1A** | 1-5 | Search, Charts, AI Analysis, Watchlist, Paper Trading |
| **Phase 1B** | 6-9 | Audit Trail, Export/Import, Cost Tracker, Market Context |
| **Phase 2** | 10-14 | Move Analysis, Second Opinion, Learning Mode, Alerts, Journal |
| **Polish** | 15 | Final integration and optimization |

**Total: 16 prompts** to build the complete AI Stock Analysis Dashboard.

Each prompt builds on the previous one. Execute them in order for best results.
