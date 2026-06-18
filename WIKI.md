# Leaps2.0 — Project Reference Wiki

> **How to pin in VS Code:** Open this file → right-click the tab → **Pin Tab**. It stays visible across file switches.

---

## Table of Contents

1. [What This Tool Does](#1-what-this-tool-does)
2. [Scan Pipeline — 8 Stages](#2-scan-pipeline--8-stages)
3. [Ticker Universe](#3-ticker-universe)
4. [Filters — What Gets Through](#4-filters--what-gets-through)
5. [Spread Construction](#5-spread-construction)
6. [ML Model (XGBoost)](#6-ml-model-xgboost)
7. [Sentiment Analysis (FinBERT)](#7-sentiment-analysis-finbert)
8. [Fundamentals Scoring](#8-fundamentals-scoring)
9. [Risk Score (Composite)](#9-risk-score-composite)
10. [Data Sources & Clients](#10-data-sources--clients)
11. [Storage & Output](#11-storage--output)
12. [API Endpoints](#12-api-endpoints)
13. [Scheduler](#13-scheduler)
14. [Key Settings & Defaults](#14-key-settings--defaults)
15. [Effective Use — Expectations & Requirements](#15-effective-use--expectations--requirements)
16. [Common Operations (Quick Reference)](#16-common-operations-quick-reference)
17. [Known Limitations & Pitfalls](#17-known-limitations--pitfalls)

---

## 1. What This Tool Does

Leaps2.0 is a **systematic options scanning and ML ranking platform** for LEAPS and vertical spreads. Given a universe of tickers, it:

1. Fetches live options chains (Schwab real-time or yfinance delayed)
2. Constructs tradeable spread candidates (bull call, bear put, LEAPS single-leg)
3. Scores each candidate on fundamentals, news sentiment, and a trained XGBoost model
4. Returns a ranked list of the best opportunities — filtered, diverse, and explained

It is **not a trade executor** — it surfaces candidates with their scores and reasoning; you decide what to trade.

---

## 2. Scan Pipeline — 8 Stages

Each scan runs these stages in sequence per-symbol, then aggregates:

| Stage | What Happens | Key Files |
|-------|-------------|-----------|
| **1. Universe** | Resolve symbol list from filters or defaults | `scanner/universe.py` |
| **2. Chains** | Fetch live options data (Schwab → yfinance fallback) | `data/schwab_client.py`, `data/yfinance_client.py` |
| **3. Filter + Construct** | Apply liquidity gates; build spread candidates | `scanner/options_filter.py`, `scanner/spread_constructor.py` |
| **4. Fundamentals** | Fetch FMP data; compute fundamental score 0–100 | `data/fmp_client.py`, `scanner/fundamentals_scorer.py` |
| **5. Sentiment** | Fetch news (yfinance + SEC EDGAR); run FinBERT | `sentiment/`, `data/edgar_client.py` |
| **6. ML Inference** | XGBoost spread_quality_score 0–100 | `ml/model.py`, `ml/features.py` |
| **7. Risk Score** | 5-factor composite risk assessment | `scanner/risk_scorer.py` |
| **8. Rank & Return** | Sort by ML score; enforce per-symbol diversity cap | `scanner/scanner.py` |

Outputs: top N `RankedSpread` objects, including all scores, greeks, and metadata.

---

## 3. Ticker Universe

**Default universe: ~587 symbols** — deduplicated union of 5 groups.

| Group | Count | Examples |
|-------|-------|---------|
| `nasdaq_100` | ~98 | AAPL, MSFT, NVDA, META, AMZN |
| `nasdaq_extended` | ~50 | SMCI, ARM, SNOW, COIN, SNAP |
| `sp500` | ~504 | Full S&P 500 across all GICS sectors |
| `msci` | ~90 | TSM, ASML, SAP, BABA (ADRs + intl ETFs) |
| `etfs` | ~70 | SPY, QQQ, XLF, TLT, GLD, USO |

**Selection priority:**
1. If `filters.symbols` set → use those (max 100)
2. If `filters.index_groups` set → union of named groups
3. Otherwise → all 587

---

## 4. Filters — What Gets Through

### Hard Liquidity Gates (applied to every leg)

| Filter | Default | Effect |
|--------|---------|--------|
| Volume | >= 100 | Low-volume contracts rejected |
| Open interest | >= 500 | Illiquid strikes rejected |
| Bid-ask spread % | <= 15% | `(ask - bid) / mid` |
| DTE (non-LEAPS) | 30 – 730 days | Standard spreads window |
| DTE (LEAPS) | 365 – 730 days | Long-dated single-leg |
| Bid and ask | Both > 0 | No stale quotes |

### Spread-Level Gates

| Filter | Default | Notes |
|--------|---------|-------|
| Delta | 0.0 – 1.0 | No default restriction; set 0.4–0.7 for directional setups |
| IV rank | 10 – 70 | Prefer lower IV for buying structures |
| Max net debit | None | Absolute premium cap |
| Max debit % of spread | None | e.g. 0.5 = debit cannot exceed 50% of width |
| Probability of profit | >= 0.0 | PoP derived from Black-Scholes N(d2) |
| Min fundamental score | >= 0.0 | 0–100 composite |
| Min sentiment score | >= 0.0 | 0–100 (neutral = 50) |
| Min ML quality score | >= 0.0 | 0–100 from XGBoost |

### Output Cap

- Max total results: **100** per scan
- Max per symbol: **3** spreads (diversity cap — enforced after ranking)

---

## 5. Spread Construction

Three structure types:

| Type | Description | Max Loss | Max Profit |
|------|-------------|----------|-----------|
| `BULL_CALL_SPREAD` | Long lower call + short higher call | Net debit | Width - debit |
| `BEAR_PUT_SPREAD` | Long higher put + short lower put | Net debit | Width - debit |
| `LEAP` | Deep ITM call (delta >= 0.70), no short leg | Premium paid | Uncapped |

**Greeks calculation:**
- Schwab: broker-calculated (preferred, no approximation needed)
- yfinance: Black-Scholes (risk-free rate hardcoded at 5%; scipy.stats.norm)

**Probability of Profit:**
```
PoP = N(d2)  where  d2 = (ln(S/K) - σ²T/2) / (σ√T)
```

---

## 6. ML Model (XGBoost)

### Algorithm

`XGBoost Regressor` wrapped in a scikit-learn `Pipeline` with `StandardScaler` preprocessing.
Predicts a continuous `spread_quality_score` (0–100), clipped at inference time.

### 23 Input Features

**Options Mechanics (6)**
- `iv_rank` — IV percentile in 52-week range
- `iv_percentile` — same formula, kept as separate feature
- `bid_ask_spread_pct` — liquidity quality of long leg
- `delta`, `gamma`, `theta_per_day` — broker or BS greeks

**Spread Structure (5)**
- `dte` — days to expiration
- `moneyness` — (strike - spot) / spot
- `spread_width_pct` — width as fraction of spot price
- `max_risk_reward_ratio` — max_profit / max_loss
- `net_debit_pct_of_spread` — debit / width (1.0 for single-leg)

**Volatility (2)**
- `iv_vs_hv_ratio` — IV / 30-day historical vol (yfinance 1y daily bars)
- `iv_skew` — placeholder (0.0; not yet implemented)

**Fundamentals (5)**
- `pe_ratio` (capped at 100), `revenue_growth`, `debt_to_equity`, `gross_margin`
- `fundamental_score` — 0–100 composite (see §8)

**Sentiment (2)**
- `sentiment_score` — 0–100 (neutral = 50)
- `sentiment_compound` — avg_positive - avg_negative

**Technical Context (3)**
- `price_vs_52w_high_pct`, `price_vs_52w_low_pct`
- `sector_relative_strength` — placeholder (0.5)

### Training

```bash
python -m backend.ml.train --data-path backend/ml/data/spread_outcomes.db --trials 50
```

- Hyperparameter search via **Optuna** (50 trials, minimize MSE)
- Cross-validation: `TimeSeriesSplit(5)` — respects temporal ordering
- Tuned params: `n_estimators`, `max_depth`, `learning_rate`, `subsample`, `colsample_bytree`, `reg_alpha`, `reg_lambda`
- Artifacts saved: `ml/artifacts/spread_ranker.joblib`, `ml/artifacts/feature_scaler.joblib`

### Cold Start / Placeholder Mode

Until ~500 labeled outcomes exist, model runs a simple heuristic:
```
score = 40 + PoP * 20 + bid_ask_quality * 20 + noise(-5, 5)
confidence = 0.3  (low — signals untrained)
```
The system is functional from Day 1 but ranking is not meaningful until real training.

### Outcome Logging

After every scan, the **top 50** ranked spreads are written to `backend/ml/data/spread_outcomes.db` (`spread_outcomes` table) with `outcome_score = NULL`. Labels are applied post-expiry via a separate labeling pipeline.

---

## 7. Sentiment Analysis (FinBERT)

### Model

**ProsusAI/finbert** — BERT-base (110M params) fine-tuned on financial news.
Downloaded once to `~/.cache/huggingface/` (~450 MB). Runs on CPU by default.

### Input Sources

1. **yfinance** ticker news — up to 20 articles per ticker
2. **SEC EDGAR** — 8-K (material events) + 10-Q filings, 14-day lookback, up to 5 per form type

Headlines deduplicated by first 80 characters.

### Scoring

Per article: `forward pass → softmax → {positive, negative, neutral}` (sum = 1.0)

Aggregation across articles:
```
avg_compound   = mean(positive) - mean(negative)
sentiment_score = ((avg_compound + 1) / 2) * 100
```
Maps: −1 → 0, 0 → 50, +1 → 100. **Neutral default = 50** (no articles or inference failure).

### Performance Notes

- Single-threaded (FinBERT is not thread-safe); runs in `ThreadPoolExecutor(max_workers=1)`
- Batched at 16 texts; async wrapper hides latency
- Cached 1 hour in Redis (key: `sentiment_v2:{symbol}`)
- Sentiment is the **slowest stage** for large universes

---

## 8. Fundamentals Scoring

Source: **Financial Modeling Prep (FMP)** free tier (250 calls/day; 24h cache).

6-factor weighted composite (0–100):

| Factor | Weight | Score Logic |
|--------|--------|-------------|
| PE ratio | 15% | <15: 100 → >40: approaching 0 |
| Revenue + Earnings growth YoY | 25% | >=30%: 100 → <0%: reduced |
| Debt-to-equity | 20% | <0.5: 90+ → >3: near 0 |
| Gross + operating margin | 20% | >=60% gross: 100; scaled below |
| Return on equity | 10% | >=40%: 100 → <0: 20+ |
| FCF yield | 10% | >=8%: 100 → <0: 20+ |

Composite = weighted average. Missing fields default to neutral mid-scores, not zeros (prevents penalising data gaps).

---

## 9. Risk Score (Composite)

**Not a filter** — an output field on each `RankedSpread` for human review.

```
composite_risk_score =
    (100 - iv_rank) * 0.25       # lower IV = less premium risk
  + bid_ask_quality  * 0.20       # tighter spread = easier entry/exit
  + fundamental_score * 0.25      # company health
  + sentiment_score  * 0.15       # news backdrop
  + liquidity_score  * 0.15       # OI + volume depth
```

`liquidity_score = min(100, (OI / 1000) * 50 + (volume / 500) * 50)`

Higher is better. Range: 0–100.

---

## 10. Data Sources & Clients

| Client | What It Fetches | Rate Limit | Cache TTL | Fallback |
|--------|----------------|-----------|-----------|---------|
| **Schwab** | Real-time quotes, chains, broker greeks | 8 concurrent, 15s timeout | None (live) | → yfinance |
| **yfinance** | Delayed quotes, chains, news, historical OHLCV | 20 concurrent, 12s timeout | 60s / 300s | None (primary fallback) |
| **FMP** | Fundamentals (PE, margins, D/E, FCF, earnings) | 250 calls/day; 1 concurrent | 24h | yfinance D/E ratio |
| **SEC EDGAR** | 8-K and 10-Q filing headlines | 5 concurrent, 10 req/s | None | Silently skipped |

**Historical volatility** (for IV rank): 1-year daily bars from yfinance → 30-day rolling HV annualised (252 trading days).

**Risk-free rate** (Black-Scholes, yfinance path only): hardcoded at **5%** (approximate T-bill rate).

---

## 11. Storage & Output

| Store | Location | What's In It | Retention |
|-------|----------|-------------|----------|
| **Redis cache** | `redis://localhost:6379` | Quotes (60s), chains (300s), fundamentals (24h), sentiment (1h) | TTL auto-expiry |
| **SQLite ML DB** | `backend/ml/data/spread_outcomes.db` | 23-feature vectors per spread candidate, outcome labels (post-expiry), P&L snapshots | Manual; grows ~50 rows/scan |
| **Scan results JSON** | `logs/scheduled_scans/results_{ts}.json` | Full `ScannerResult` with all `RankedSpread` details | Manual cleanup |
| **FinBERT weights** | `~/.cache/huggingface/` | Model weights (~450 MB) | Permanent (HuggingFace cache) |
| **ML artifacts** | `ml/artifacts/spread_ranker.joblib` | Trained XGBoost model + scaler | Overwritten on each retrain |
| **Schwab token** | `backend/.schwab_token.enc` (encrypted) | OAuth refresh token | Valid 7 days; must re-auth |

### SQLite Schema (key tables)

**`spread_outcomes`** — one row per logged spread candidate:
- `scan_id`, `symbol`, `spread_type`, `expiration`, `entry_date`
- `outcome_score` — NULL until labeled post-expiry
- `features_json` — all 23 features at time of scan
- `entry_net_debit`, `spot_at_entry`, `horizon_days` (30)

**`price_snapshots`** — P&L tracking post-entry:
- `outcome_id` → FK to spread_outcomes
- `days_since_entry`, `pnl_pct`, `outcome_score` (normalised 0–100)

---

## 12. API Endpoints

Base: `http://localhost:8000`

| Method | Path | Description | Rate Limit |
|--------|------|-------------|-----------|
| POST | `/api/v1/scanner/scan` | Submit a scan job; returns `scan_id` | 5/min |
| GET | `/api/v1/scanner/scan/{scan_id}` | Poll job status + results | — |
| GET | `/api/v1/scanner/universe` | List all 587 default symbols | — |
| GET | `/api/v1/scanner/filters/defaults` | Fetch default filter values | — |
| GET | `/api/v1/sentiment/{symbol}` | Score one ticker's sentiment | 20/min |
| POST | `/api/v1/sentiment/batch` | Score up to 20 tickers | 20/min |
| GET | `/api/v1/ml/status` | Is model trained? placeholder? | — |
| GET | `/api/v1/ml/feature-importance` | XGBoost feature importances | — |
| GET | `/api/v1/ml/db-stats` | Outcome DB stats (labeled/unlabeled/ready) | — |
| GET | `/api/v1/ml/ticker-snapshot-history` | P&L history for a symbol | — |
| GET | `/health` | Server health + Schwab token days remaining | Public |
| GET | `/docs` | Swagger UI | Public |

---

## 13. Scheduler

**File:** `backend/scripts/scheduled_scan.py`

Standalone (no FastAPI required). Used for cron/Task Scheduler runs.

```bash
# Activate venv first
backend\.venv\Scripts\activate

# Run a full scan
python -m backend.scripts.scheduled_scan

# Dry-run (resolve filters only, no actual scan)
python -m backend.scripts.scheduled_scan --dry-run

# Custom filter overrides
python -m backend.scripts.scheduled_scan --config scan_config.json
```

**Output files per run:**
- `logs/scheduled_scans/scan_{YYYYMMDD_HHMMSS}.log`
- `logs/scheduled_scans/results_{YYYYMMDD_HHMMSS}.json`

Current scan schedule: configured in `setup_scheduler.ps1` (Windows Task Scheduler).

---

## 14. Key Settings & Defaults

All settings live in `backend/config/settings.py` and load from `backend/.env`.

```
# Data sources
SCHWAB_APP_KEY        = ""
SCHWAB_APP_SECRET     = ""
SCHWAB_TOKEN_PATH     = backend/.schwab_token.json
SCHWAB_CALLBACK_URL   = https://127.0.0.1:8182/
SCHWAB_TOKEN_KEY      = ""          # Fernet key; empty = no encryption
FMP_API_KEY           = ""

# Scanner thresholds
SCANNER_MIN_VOLUME              = 100
SCANNER_MIN_OPEN_INTEREST       = 500
SCANNER_MAX_BID_ASK_SPREAD_PCT  = 0.15
SCANNER_MIN_DTE                 = 30
SCANNER_LEAPS_MIN_DTE           = 365

# ML
ML_MODEL_PATH               = ml/artifacts/spread_ranker.joblib
ML_FEATURE_SCALER_PATH      = ml/artifacts/feature_scaler.joblib

# FinBERT
FINBERT_MODEL_NAME  = ProsusAI/finbert
FINBERT_BATCH_SIZE  = 16
FINBERT_DEVICE      = cpu           # set "cuda" if GPU available

# Cache TTLs (seconds)
CACHE_TTL_QUOTES        = 60
CACHE_TTL_CHAINS        = 300
CACHE_TTL_FUNDAMENTALS  = 86400
CACHE_TTL_SENTIMENT     = 3600

# API
APP_HOST         = 0.0.0.0
APP_PORT         = 8000
RATE_LIMIT_SCAN  = 5/minute
REVIEW_PASSWORD  = ""              # enables HTTP Basic Auth gate if set
```

---

## 15. Effective Use — Expectations & Requirements

### Data Requirements

| Component | Minimum to Function | Optimal |
|-----------|-------------------|---------|
| Options chains | yfinance (free, 15-min delay) | Schwab token (real-time) |
| Fundamentals | FMP free key (250 calls/day) | Same (24h cache makes it sufficient) |
| Sentiment | No key needed (yfinance news + SEC EDGAR) | Same |
| ML ranking | Day 1: placeholder heuristic | ~500 labeled spread outcomes post-expiry |
| Historical IV | yfinance 1-year daily bars (free) | Same |

### ML Training Readiness

| Labeled Rows | Model State |
|-------------|-------------|
| 0 – 99 | Placeholder only; ranking is noise-level |
| 100 – 499 | Warning: training possible but high variance |
| 500+ | Training recommended; signal begins to emerge |
| 1,000+ | Model becomes reliably discriminative |

Check readiness: `GET /api/v1/ml/db-stats`

Labels are applied **post-expiry** — you need to run the outcome labeling pipeline after each batch of contracts expires. This is the critical feedback loop.

### Scan Performance

A full 587-symbol scan takes **~10 minutes** (dominated by FinBERT inference and yfinance chain fetches). Expect:
- ~65,000 spread candidates evaluated
- ~500–1,000 passing all filters
- Top 100 returned

To speed up: restrict `index_groups` or `symbols` in filters; use Schwab (fewer retries); run on GPU for FinBERT.

### Schwab Token Rotation

- **Must be renewed every 7 days** — no exceptions on their developer tier
- The backend logs `WARNING` at <= 2 days, `ERROR` at <= 1 day remaining
- Check anytime: `GET /health` → `schwab_token_days_remaining`
- Re-auth: see §16

### FMP Free Tier

- 250 calls/day hard cap
- 24-hour cache means: once a ticker is fetched, no further calls for 24h
- Full 587-symbol universe = 587 calls; will **exceed** the free tier in one scan if cold cache
- Mitigation: only use FMP for tickers that pass earlier (liquidity) filters; or upgrade FMP tier

### When Results Are Not Trustworthy

- ML score in placeholder mode (check `/api/v1/ml/status`)
- Schwab token expired → greeks are Black-Scholes approximations (less accurate)
- FMP rate limit hit → fundamental scores default to neutral mid-scores
- FinBERT failed to load → sentiment scores default to 50 (neutral)

---

## 16. Common Operations (Quick Reference)

### Activate venv

```bash
cd "C:\Users\Apprentice\Desktop\Projects\Leaps2.0"
backend\.venv\Scripts\activate
```

### Schwab OAuth (every 7 days)

```bash
python -m backend.scripts.schwab_auth
# Browser opens → log in → token saved automatically
# Restart backend after
```

### Start the backend

```bash
start.bat
# or manually:
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Run a manual scan

```bash
python -m backend.scripts.scheduled_scan
```

### Check Schwab token days

```bash
curl http://localhost:8000/health
# → { "schwab_token_days_remaining": 4.2, ... }
```

### Check ML DB stats

```bash
curl http://localhost:8000/api/v1/ml/db-stats
```

### Retrain ML model

```bash
python -m backend.ml.train \
  --data-path backend/ml/data/spread_outcomes.db \
  --trials 50
```

### Generate Fernet encryption key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Paste output into SCHWAB_TOKEN_KEY in backend/.env
```

---

## 17. Known Limitations & Pitfalls

| Issue | Impact | Mitigation |
|-------|--------|-----------|
| Schwab token expires every 7 days | Falls back to yfinance (delayed, worse greeks) | Calendar reminder; check `/health` |
| FMP 250 call/day cap | Fundamental scores go neutral on cache miss beyond cap | 24h cache; restrict universe size |
| FinBERT single-threaded | Sentiment is slowest stage at scale | Restrict universe; use GPU (`FINBERT_DEVICE=cuda`) |
| ML cold start | Rankings meaningless until ~500 labeled outcomes | Accept placeholder for first months; prioritise labeling |
| Outcome labeling not automated | DB fills with NULL outcome_scores indefinitely | Must run labeling pipeline post-expiry manually |
| IV skew placeholder | `iv_skew = 0.0` for all spreads | Will underweight skew dynamics; acceptable until implemented |
| Sector relative strength placeholder | `sector_relative_strength = 0.5` for all | No sector momentum signal yet |
| In-memory scan job store | Results lost on app restart | Fetch results JSON from `logs/scheduled_scans/` |
| Unicode arrow (`→`) in log messages | Windows CP1252 encoding error on console | Already reproduced; fix: set `PYTHONIOENCODING=utf-8` or replace arrow with `->` in scanner.py log strings |
| Black-Scholes risk-free rate hardcoded | Greeks slightly off as rates change | Update `RISK_FREE_RATE` in `yfinance_client.py` if rates shift materially |

---

*Last updated: 2026-04-02*
