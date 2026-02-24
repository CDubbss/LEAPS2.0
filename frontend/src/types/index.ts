// TypeScript interfaces mirroring the backend Pydantic models

export type OptionType = "call" | "put";
export type SpreadType = "bull_call" | "bear_put" | "leap_call" | "leap_put" | "leaps_spread_call";

export interface OptionQuote {
  symbol: string;
  underlying: string;
  expiration: string;
  strike: number;
  option_type: OptionType;
  bid: number;
  ask: number;
  mid: number;
  last: number;
  volume: number;
  open_interest: number;
  implied_volatility: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho: number;
}

export interface SpreadCandidate {
  underlying: string;
  spread_type: SpreadType;
  expiration: string;
  dte: number;
  long_leg: OptionQuote;
  short_leg: OptionQuote | null;
  net_debit: number;
  max_profit: number;
  max_loss: number;
  breakeven: number;
  probability_of_profit: number;
  bid_ask_quality_score: number;
  iv_rank: number;
  spread_width: number;
}

export interface FundamentalData {
  symbol: string;
  company_name: string;
  sector: string;
  industry: string;
  market_cap: number;
  pe_ratio: number | null;
  forward_pe: number | null;
  peg_ratio: number | null;
  price_to_book: number | null;
  price_to_sales: number | null;
  revenue_growth_yoy: number | null;
  earnings_growth_yoy: number | null;
  debt_to_equity: number | null;
  current_ratio: number | null;
  gross_margin: number | null;
  operating_margin: number | null;
  net_margin: number | null;
  return_on_equity: number | null;
  return_on_assets: number | null;
  free_cash_flow_yield: number | null;
  next_earnings_date: string | null;
  days_to_earnings: number | null;
  fundamental_score: number | null;
}

export interface ArticleSentiment {
  headline: string;
  url: string;
  published_at: string;
  source: string;
  positive: number;
  negative: number;
  neutral: number;
  label: "positive" | "negative" | "neutral";
}

export interface OHLCBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TickerSentiment {
  symbol: string;
  articles_analyzed: number;
  avg_positive: number;
  avg_negative: number;
  avg_neutral: number;
  avg_compound: number;
  sentiment_label: string;
  sentiment_score: number;
  top_headlines: string[];
  analyzed_at: string;
  article_sentiments: ArticleSentiment[];
}

export interface MLPrediction {
  spread_quality_score: number;
  expected_return_pct: number;
  probability_of_profit: number;
  confidence: number;
  feature_importances: Record<string, number>;
  is_placeholder: boolean;
}

export interface RiskScore {
  composite_score: number;
  iv_rank_component: number;
  bid_ask_component: number;
  fundamental_component: number;
  sentiment_component: number;
  liquidity_component: number;
  breakdown: Record<string, number>;
}

export interface RankedSpread {
  rank: number;
  spread: SpreadCandidate;
  fundamentals: FundamentalData;
  sentiment: TickerSentiment;
  ml_prediction: MLPrediction;
  risk_score: RiskScore;
}

export interface ScannerFilters {
  symbols: string[] | null;
  strategies: SpreadType[];
  min_dte: number;
  max_dte: number;
  leaps_min_dte: number;
  leaps_max_dte: number;
  min_iv_rank: number;
  max_iv_rank: number;
  min_volume: number;
  min_open_interest: number;
  max_bid_ask_spread_pct: number;
  min_fundamental_score: number;
  min_sentiment_score: number;
  min_probability_of_profit: number;
  min_ml_quality_score: number;
  max_results: number;
  target_spread_widths: number[];
  max_spread_width: number | null;
  max_debit_pct_of_spread: number;
  max_net_debit: number | null;
  min_long_delta: number;
  max_long_delta: number;
}

export interface ScannerResult {
  scan_id: string;
  scan_time: string;
  filters_used: ScannerFilters;
  total_candidates_evaluated: number;
  results: RankedSpread[];
  scan_duration_seconds: number;
}

export interface OptionsChain {
  underlying: string;
  spot_price: number;
  quote_time: string;
  expirations: string[];
  calls: OptionQuote[];
  puts: OptionQuote[];
}

export const DEFAULT_FILTERS: ScannerFilters = {
  symbols: null,
  strategies: ["leap_call", "leaps_spread_call"],
  min_dte: 30,
  max_dte: 90,
  leaps_min_dte: 365,
  leaps_max_dte: 730,
  min_iv_rank: 10,
  max_iv_rank: 70,
  min_volume: 100,
  min_open_interest: 500,
  max_bid_ask_spread_pct: 0.15,
  min_fundamental_score: 40,
  min_sentiment_score: 35,
  min_probability_of_profit: 0.45,
  min_ml_quality_score: 45,
  max_results: 50,
  target_spread_widths: [],
  max_spread_width: null,
  max_debit_pct_of_spread: 0.25,
  max_net_debit: null,
  min_long_delta: 0.0,
  max_long_delta: 1.0,
};

export const SPREAD_TYPE_LABELS: Record<SpreadType, string> = {
  bull_call: "Bull Call",
  bear_put: "Bear Put",
  leap_call: "LEAPS Call",
  leap_put: "LEAPS Put",
  leaps_spread_call: "LEAPS Spread Call",
};
