import axios from "axios";
import type {
  FundamentalData,
  OptionsChain,
  ScannerFilters,
  ScannerResult,
  TickerSentiment,
} from "@/types";

const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
  timeout: 120_000, // 2 min — scans can take 30-60s
});

// Request interceptor for logging
api.interceptors.request.use((config) => {
  console.debug(`[API] ${config.method?.toUpperCase()} ${config.url}`);
  return config;
});

// Response interceptor for error normalization
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const message =
      error.response?.data?.detail ||
      error.response?.data?.message ||
      error.message ||
      "Unknown error";
    return Promise.reject(new Error(message));
  }
);

export const scannerApi = {
  runScan: (filters: ScannerFilters): Promise<ScannerResult> =>
    api.post("/scanner/scan", filters).then((r) => r.data),

  getDefaultFilters: (): Promise<ScannerFilters> =>
    api.get("/scanner/filters/defaults").then((r) => r.data),

  getDefaultUniverse: (): Promise<string[]> =>
    api.get("/scanner/universe").then((r) => r.data),
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

export const mlApi = {
  getFeatureImportance: (): Promise<Record<string, number>> =>
    api.get("/ml/feature-importance").then((r) => r.data),

  getStatus: (): Promise<{ is_trained: boolean; mode: string; message: string }> =>
    api.get("/ml/status").then((r) => r.data),
};

export const healthApi = {
  check: () => api.get("/health", { baseURL: "" }).then((r) => r.data),
};
