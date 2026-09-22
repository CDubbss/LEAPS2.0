import axios from "axios";
import type {
  FundamentalData,
  OHLCBar,
  OptionsChain,
  ScanJob,
  ScannerFilters,
  ScannerResult,
  TickerSentiment,
} from "@/types";

const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
  timeout: 600_000, // 10 min — full 587-symbol scans; status polls are near-instant
});

// Request interceptor — debug logging in development only
api.interceptors.request.use((config) => {
  if (import.meta.env.DEV) {
    console.debug(`[API] ${config.method?.toUpperCase()} ${config.url}`);
  }
  return config;
});

// Response interceptor for error normalization.
// FastAPI 422s put a LIST of {loc, msg, ...} objects in detail — flatten those
// to readable text instead of letting them stringify as "[object Object]".
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error.response?.data?.detail;
    let message: string;
    if (Array.isArray(detail)) {
      message = detail
        .map((d) => {
          const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "";
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join("; ");
    } else if (typeof detail === "string") {
      message = detail;
    } else {
      message =
        error.response?.data?.message || error.message || "Unknown error";
    }
    return Promise.reject(new Error(message));
  }
);

export const scannerApi = {
  startScan: (filters: ScannerFilters): Promise<ScanJob> =>
    api.post("/scanner/scan", filters).then((r) => r.data),

  getScanStatus: (scanId: string): Promise<ScanJob> =>
    api.get(`/scanner/scan/${scanId}`).then((r) => r.data),

  getDefaultFilters: (): Promise<ScannerFilters> =>
    api.get("/scanner/filters/defaults").then((r) => r.data),

  getDefaultUniverse: (): Promise<string[]> =>
    api.get("/scanner/universe").then((r) => r.data),

  // Presets are stored server-side (SQLite) so they survive browser data
  // clearing and are shared between the dev server and the built app.
  getPresets: (): Promise<Record<string, ScannerFilters>> =>
    api.get("/scanner/presets").then((r) => r.data),

  savePreset: (name: string, filters: ScannerFilters): Promise<void> =>
    api.put(`/scanner/presets/${encodeURIComponent(name)}`, filters).then(() => undefined),

  deletePreset: (name: string): Promise<void> =>
    api.delete(`/scanner/presets/${encodeURIComponent(name)}`).then(() => undefined),
};

export const optionsApi = {
  getExpirations: (symbol: string): Promise<string[]> =>
    api.get(`/options/expirations/${symbol}`).then((r) => r.data),

  getChain: (symbol: string, expiration?: string): Promise<OptionsChain> =>
    api
      .get(`/options/chain/${symbol}`, { params: { expiration } })
      .then((r) => r.data),

  getQuote: (symbol: string): Promise<Record<string, number>> =>
    api.get(`/options/quote/${symbol}`).then((r) => r.data),

  getHistoricalOHLC: (symbol: string, period = "1y"): Promise<OHLCBar[]> =>
    api.get(`/options/historical/${symbol}/ohlc?period=${period}`).then((r) => r.data),
};

export const sentimentApi = {
  getTickerSentiment: (symbol: string): Promise<TickerSentiment> =>
    api.get(`/sentiment/${symbol}`).then((r) => r.data),

  getBatchSentiment: (
    symbols: string[]
  ): Promise<Record<string, TickerSentiment>> =>
    api.post("/sentiment/batch", symbols).then((r) => r.data),
};

export const fundamentalsApi = {
  getFundamentals: (symbol: string): Promise<FundamentalData> =>
    api.get(`/fundamentals/${symbol}`).then((r) => r.data),
};

export type BucketSpread = {
  id: number;
  symbol: string;
  spread_type: string;
  entry_date: string;
  expiration: string;
  outcome_score: number;
  peak_pnl_pct: number | null;
  peak_pnl_dollars: number | null;
  label_source: string | null;
  best_sell_days: number | null;
};

export type SpreadDetail = {
  id: number;
  symbol: string;
  spread_type: string;
  entry_date: string;
  expiration: string;
  logged_at: string;
  outcome_score: number | null;
  peak_pnl_pct: number | null;
  peak_pnl_dollars: number | null;
  label_source: string | null;
  best_sell_days: number | null;
  // Entry prices
  entry_net_debit: number | null;
  long_mid_at_entry: number | null;
  short_mid_at_entry: number | null;
  spot_at_entry: number | null;
  spot_at_best_day: number | null;
  best_day_date: string | null;
  spot_today: number | null;
  today_date: string | null;
  credit_at_best_day: number | null;
  credit_today: number | null;
  spread_width: number | null;
  // Legs
  long_strike: number | null;
  long_option_type: string | null;
  short_strike: number | null;
  short_option_type: string | null;
  // Greeks
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  iv_rank: number | null;
  iv_pct: number | null;
  iv_vs_hv: number | null;
  bid_ask_pct: number | null;
  // Structure
  dte: number | null;
  moneyness: number | null;
  spread_width_pct: number | null;
  max_risk_reward: number | null;
  net_debit_pct_of_spread: number | null;
  // Fundamentals
  pe_ratio: number | null;
  revenue_growth: number | null;
  debt_to_equity: number | null;
  gross_margin: number | null;
  fundamental_score: number | null;
  // Sentiment
  sentiment_score: number | null;
  sentiment_compound: number | null;
  // Price context
  price_vs_52w_high: number | null;
  price_vs_52w_low: number | null;
};

export type TickerSpread = {
  id: number;
  entry_date: string;
  spread_type: string;
  entry_net_debit: number;
  spot_at_entry: number;
  snapshots: Array<{
    days_since_entry: number;
    snapshot_date: string;
    pnl_pct: number;
    current_value: number;
  }>;
};

export const mlApi = {
  getFeatureImportance: (): Promise<Record<string, number>> =>
    api.get("/ml/feature-importance").then((r) => r.data),

  getStatus: (): Promise<{ is_trained: boolean; mode: string; message: string }> =>
    api.get("/ml/status").then((r) => r.data),

  getDbStats: (): Promise<{
    total: number;
    labeled: number;
    unlabeled: number;
    snapshots: number;
    training_threshold: number;
    ready_to_train: boolean;
    recent_scans: Array<{ date: string; scans: number; candidates: number }>;
    best_sell_days_distribution: Array<{ best_sell_days: number; count: number }>;
    score_distribution: Array<{ bucket: number; count: number }>;
    snapshot_intervals: Array<{ days_since_entry: number; count: number }>;
    avg_sell_days_by_type: Array<{ spread_type: string; avg_days: number; count: number }>;
    tickers_with_snapshots: string[];
  }> => api.get("/ml/db-stats").then((r) => r.data),

  getTickerSnapshotHistory: (symbol: string): Promise<{ symbol: string; spreads: TickerSpread[] }> =>
    api.get(`/ml/ticker-snapshot-history?symbol=${encodeURIComponent(symbol)}`).then((r) => r.data),

  getScoreBucket: (bucket: number): Promise<BucketSpread[]> =>
    api.get(`/ml/score-bucket?bucket=${bucket}`).then((r) => r.data),

  getSpreadDetail: (id: number): Promise<SpreadDetail> =>
    api.get(`/ml/spread/${id}`).then((r) => r.data),
};

export type PositionCreate = {
  symbol: string;
  spread_type: string;
  long_strike: number;
  long_option_type: string;
  short_strike: number | null;
  short_option_type: string | null;
  expiration: string;
  entry_date: string;
  entry_debit: number;
  contracts: number;
  notes?: string | null;
  // Ted (earnings IV-buildup) positions only
  earnings_date?: string | null;
  exit_by?: string | null;
};

export type Position = PositionCreate & {
  id: number;
  status: "open" | "closed";
  exit_date: string | null;
  exit_value: number | null;
  notes: string | null;
  current_value: number | null;
  pnl_pct: number | null;
  pnl_dollars: number | null;
  target_pct: number;
  target_hit: boolean;
  stop_hit: boolean;
  days_held: number;
  dte: number;
};

export const positionsApi = {
  list: (refresh = true): Promise<Position[]> =>
    api.get(`/positions?refresh=${refresh}`).then((r) => r.data),

  create: (body: PositionCreate): Promise<Position> =>
    api.post("/positions", body).then((r) => r.data),

  update: (
    id: number,
    body: Partial<{
      status: "open" | "closed";
      exit_date: string;
      exit_value: number;
      notes: string;
      contracts: number;
      expiration: string;
      entry_date: string;
      entry_debit: number;
      long_strike: number;
      short_strike: number;
    }>
  ): Promise<Position> => api.patch(`/positions/${id}`, body).then((r) => r.data),

  remove: (id: number): Promise<void> => api.delete(`/positions/${id}`).then(() => undefined),
};

// ---------------------------------------------------------------------------
// The Ted — earnings IV-buildup gate checker
// ---------------------------------------------------------------------------

export type TedCandidate = {
  symbol: string;
  earnings_date: string;
  days_out: number;
  ideal: boolean;
};

export type TedGate = {
  num: number;
  name: string;
  status: "pass" | "warn" | "fail" | "manual";
  detail: string;
  hard: boolean;
  auto: boolean;
};

export type TedStrikeOption = {
  strike: number;
  bid: number;
  ask: number;
  mid: number;
  open_interest: number;
  volume: number;
  iv: number;
  delta: number;
  theta: number;
  vega: number;
};

export type TedReport = {
  symbol: string;
  direction: string;
  option_type: string;
  days_out: number | null;
  gates: TedGate[];
  iv_score: number;
  dir_score: number;
  hard_fails: number[];
  verdict: "TRADE" | "CAUTION" | "WEAK" | "NO_TRADE";
  verdict_detail: string;
  sizing_notes: string[];
  recommended_contracts: number;
  total_cost: number | null;
  pct_of_account: number | null;
  exit_by: string | null;
  exit_window_text: string;
};

export type TedCheckResponse = {
  report: TedReport;
  context: {
    spot: number | null;
    earnings_date: string | null;
    expiration: string | null;
    expirations_near_earnings: string[];
    option_side: "call" | "put";
    chosen_strike: number | null;
    strike_menu: TedStrikeOption[];
    sector: string | null;
    sector_etf: string | null;
    company_name: string | null;
  };
};

export type TedCheckParams = {
  direction: "bull" | "bear";
  account_balance: number;
  contracts: number;
  strike?: number;
  expiration?: string;
  expected_iv_gain?: number;
  bmo_amc?: "bmo" | "amc";
  no_contra?: boolean;
  attention_override?: boolean;
  analyst_override?: boolean;
};

export const tedApi = {
  getCandidates: (): Promise<{
    candidates: TedCandidate[];
    window: { from: string; to: string };
    source: string;
    message: string;
  }> => api.get("/ted/candidates").then((r) => r.data),

  check: (symbol: string, params: TedCheckParams): Promise<TedCheckResponse> =>
    api
      .get(`/ted/check/${encodeURIComponent(symbol)}`, { params })
      .then((r) => r.data),
};

export const healthApi = {
  check: () => api.get("/health", { baseURL: "" }).then((r) => r.data),
};
