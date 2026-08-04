# Leaps2.0 — Project Handoff

> **Read this first.** Full context for an AI assistant or maintainer picking this project up cold.
> Every factual claim here was verified against the codebase / database at the time of writing.
> **Last updated: 2026-08-04.**
>
> **Companion context files** (read alongside this):
> - `CLAUDE.md` (repo root) — how the assistant should communicate. Neutral, direct, trade-offs surfaced, no cheerleading.
> - `~/.claude/projects/C--Users-Apprentice-Desktop-Projects-Leaps2-0/memory/MEMORY.md` — index of per-topic memory notes (`project_*.md`, `user_trading_strategy.md`) with deeper detail on the labeling pipeline, Ted, data bolstering, and scan operations.
>
> **Verify before asserting.** This file ages. Check `spread_ranker_meta.json`, the DB, and the code before stating anything as current fact. Several past errors in this project came from trusting a stale number.

---

## 1. What this is and why it exists

A personal stock-options scanner + ML ranking system, built solo, for one person's actual trading. Not a product. The goal is **narrow and concrete: find high-quality option spreads and enforce exit discipline**, using free data sources wherever possible.

### The core strategy — vertical LEAPS bull call spread
Buy a lower-strike call, sell a higher-strike call, **same expiration**, 12+ months out. (Not a diagonal/PMCC — both legs share the long-dated expiry.)

- **25% cost rule**: net debit ≤ 25% of strike width → 1:3 risk/reward. A $10-wide spread costs at most $2.50 and can make $7.50.
- **Exits: +50% profit / −50% loss.** Updated 2026-07-09 (was −25%). Symmetric, so **breakeven win rate = 50%**.
- The user's framing: *"±50% are fungible — I might exit before −50% and before +50% gains."* The thresholds model typical behavior. **Don't over-engineer threshold precision**, and treat model probabilities as ranking signals rather than calibrated odds.
- **Commissions**: $13 per 10-contract spread per side ($26 round trip = $0.026/share). Baked into every target calculation via `_commission_adjusted_target()` in `label_outcomes.py`.
- Why this structure: capital efficient, defined risk (max loss = debit, locked at entry), same-expiry legs damp vega, and both legs decay together.

### Secondary strategies
- **`leaps_spread_put`** — bear put vertical at LEAPS DTE. Added 2026-07-14 when the user began running bear-market scans. (The pre-existing `bear_put` runs at 30–90 DTE, which is a different trade.)
- **"The Ted"** — earnings IV-buildup play with its own page and 14-gate checklist. See §5.

### Project goals (in priority order)
1. **Don't lose money to indiscipline.** The Positions page exists to mechanically enforce exits humans rationalize away.
2. **Find the top slice of candidates.** The ML ranker's job is separation, not prediction of exact returns.
3. **Build an honest track record.** Every scan logs candidates with the model's scan-time score so walk-forward validation is possible without look-ahead bias.
4. **Stay cheap.** yfinance (free) over paid feeds; FMP free tier accepted with its 402s.
5. **Security matters more than features** (explicit user value in `CLAUDE.md`).

---

## 2. Architecture

| Layer | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn — port **8001** (8000 is reserved for a different project on this machine) |
| Frontend | React 18 + TypeScript + Vite (**5173**) + Tailwind (dark theme), Zustand state |
| Options data | yfinance (free, ~15-min delayed). Schwab exists for chains but is **excluded from the labeler** (OAuth retry hazard, §6) |
| Fundamentals | Financial Modeling Prep — key in `backend/.env`, **never commit**. Free tier: several endpoints return 402 |
| Sentiment | yfinance news + FinBERT (ProsusAI/finbert, CPU) |
| Greeks | Computed locally, Black-Scholes via scipy (yfinance doesn't supply them) |
| ML | XGBoost regressor + classifier, Optuna HPO, TimeSeriesSplit CV |
| Storage | SQLite `backend/ml/data/spread_outcomes.db` (WAL, ~92 MB) + `backend/data/ui_presets.db`; Redis via Docker for caching |
| Startup | `start.bat` — backend + frontend + Redis. **Never use `--reload`** (kills background scan tasks mid-flight) |

**Universe**: ~587 unique symbols — Nasdaq 100, Nasdaq extended (high-beta/high-OI names), S&P 500 by GICS sector, MSCI/international ADRs, and ETFs.

### The data pipeline (the heart of the system)
1. **Scan** — 8 stages over the universe. Every surviving candidate is logged to `spread_outcomes` with a **27-feature vector**, the model's **scan-time `ml_score`**, and a **`model_version`** stamp. Plus up to 25 gate-rejected "near-miss" rows per scan.
2. **Label** (`label_outcomes`, scheduled ~9 AM) — snapshots each open spread's market value via yfinance; assigns tiered outcome labels (`interim_5d` … `interim_720d`, `expiry`) with trust weights 0.05 → 1.0; computes strategy win/loss by **first-passage** on ±50%.
3. **Train** (`train.py`) — Optuna + TimeSeriesSplit → the **ranker** (weighted-MSE regressor on 0–100 outcome scores) and the **strategy classifier** (P(hit +50% before −50%)). Artifacts to `backend/ml/artifacts/`, last 3 versions kept.
4. **Backtest** (`backtest.py --json`) — validates stored scan-time scores against realized outcomes. Read-only.

**All commands must use the venv Python:**
```bash
backend\.venv\Scripts\python.exe -m backend.ml.train
```
Plain `python -m ...` uses system Python and fails with `ModuleNotFoundError: pandas`.

---

## 3. Current state (2026-08-04)

**Models**
| Artifact | Trained | Samples | Metric |
|---|---|---|---|
| `spread_ranker.joblib` | 2026-08-03 23:54 UTC | 44,170 | Weighted MSE **240.9** (best) |
| `strategy_classifier.joblib` | 2026-08-04 00:04 UTC | 14,088 decided | AUC **0.848** |

MSE trajectory: `451.6 → 455.2 → 409.2 → 408.2 → 397.3 → 368.0 → 327.8 → 257.3 → 258.3 → 259.7 → 251.2 → 259.4 → 244.1 → 240.9`
Classifier AUC (since the honest ±50% relabel): `0.837 → 0.826 → 0.815 → 0.815 → 0.852 → 0.848`

**Database**: 52,227 rows | 45,344 labeled | 1,507 near-miss | 942 bear-put (252 decided) | ~13k rows carry regime features.
**Strategy outcome split**: ~25.4% win rate on decided rows — stable across every training run since the relabel.

**Mature labels (60d+)**: `interim_60d` 4,553 · `interim_90d` 3,524 · `expiry` 126 — **all from March–May entries**, i.e. older models.
**Trained-era rows (≥2026-07-08)**: labeled only at `interim_5d` (5,127) and `interim_10d` (11,782). See §4.2.

**Git**: on branch `feat/ted-positions-data-bolstering`, pushed to origin, working tree clean. `main` is stale since 2026-06-18. PR not yet opened.

---

## 4. ⚠️ Open issues — read before drawing conclusions

### 4.1 Backtest decile tables are era-contaminated (OPEN, highest priority)
Discovered 2026-07-30. `backtest.py` computes deciles/quintiles on **pooled** ml_scores across all model eras, but score scales drifted enormously:

| Month | mean | std |
|---|---|---|
| 2026-03 | 63.7 | **19.7** |
| 2026-05 | 50.5 | 15.0 |
| 2026-06 (placeholder era) | 60.1 | **5.9** |
| 2026-07 (trained) | 53.2 | 6.7 |

Pooling std-19.7 scores with std-5.9 scores makes deciles sort largely **by era, not by quality**. Verified: pooled deciles 6–9 are 57–67% June (placeholder) rows; decile 10 is 30% June + 24% April.

**Consequences:**
- The decile-lift, quintile hit-rate, and calibration tables **cannot be read as guidance for the current model**.
- An earlier assistant conclusion — *"scores 58–61 are actively worse, treat as a negative signal"* — was **wrong**. It was an artifact of placeholder scores clustering at 60±6. **Do not repeat it.**
- **The dollar simulation IS trustworthy**: it picks top-3 *within each scan day* and compares against random picks *from that same day*, so both sides always share a model era. Latest: **+$152,089 edge (+2.0σ)**, model 67.7% win rate vs random 17.5%.

**Fix (not implemented):** segment deciles/hit-rates by `model_version` (stamps exist since ~7/14; fall back to entry-month for older rows). The user was offered this and hasn't answered yet.

### 4.2 The current model is not yet independently validated
Every trained-era row is labeled at 5–10 days — the tiers where rank correlation is *negative* (`interim_10d` rho = −0.206 on 14,268 rows). All strong mature-tier correlations (`interim_90d` +0.82, `expiry` +0.95) belong to March–April entries scored by **older** models.

**Honest position: no verdict on the current model until July rows reach 60d+ labels.** Timeline: 30-day labels ~Aug 19, 45-day ~Sept 4, 60-day ~Oct 1.

### 4.3 Regime and bear features unproven
~13k rows carry VIX / SPY-vs-200d / sector-trend, but essentially all were collected in **one regime** (SPY ~8% above its 200-day, VIX 16–17). A model cannot learn regime-*conditional* behavior from a single regime. Bear puts: 942 rows / 252 decided, entirely in an uptrend where put spreads should lose. Neither is evaluable yet.

### 4.4 Entry debit is worst-case fill (by design, but misleading)
`net_debit = long_leg.ask - short_leg.bid` (`spread_constructor.py:79`), while all later snapshots mark **mid-to-mid**. Positions therefore start "underwater" by the full bid-ask cross. One observed spread showed −86% peak P&L where mid-to-mid was −62%.
Fine for training (uniform penalty, teaches preference for tight markets) but **logged P&L runs pessimistic**, especially on wide markets, and backtest edge numbers are conservative. Real fills with limit orders should beat it.

### 4.5 `formatDate()` off-by-one
Date-only strings are parsed as UTC and render one day early in Mountain Time (Jan 21 → "Jan 20"). Display only — stored dates are correct. Task chip spawned; not fixed.

### 4.6 Dependency vulnerabilities — triaged, not patched
See §8. 64 local advisories; ~8 actually reachable. No packages upgraded yet.

---

## 5. Features built (with file pointers)

### Scanner — `/` (`ScannerPage.tsx`, `scanner/scanner.py`)
8-stage pipeline. Filter panel with universe groups, strategy selection, DTE/IV/delta/liquidity/cost filters. Results table sorted by ML score.
- **FIT badge** — passes when net_debit/width ≤ 25%, |delta| ≤ 0.33, OI ≥ 50, volume ≥ 10, bid-ask ≤ 25%. Hover lists which checks failed.
- **CSV export**, column sorting.
- **Persistence**: zustand `persist` (localStorage `leaps-scanner`, version 1) for filters + `activeScanId`; refreshing mid-scan reattaches to the running job.
- **Presets are server-side** (`backend/data/ui_presets.db`, `GET/PUT/DELETE /api/v1/scanner/presets`); localStorage is only a warm cache. Deliberately a **separate DB** from the outcomes DB, whose labeling write-locks stalled preset reads 18–30 s.
- **Delta filter accepts negative input** and normalizes via `abs()` — put deltas are negative, so −0.33 and 0.33 mean the same thing.

### Positions tracker — `/positions` (`api/routes/positions.py`, `PositionsPage.tsx`)
Log real trades (or click "Track" on a scan result). Live yfinance pricing on demand.
- Badges: **TARGET HIT — SELL** (≥ commission-adjusted +50%), **STOP HIT** (≤ −50%), **EXIT BY <date>** → **EXIT NOW — PRINT RISK** for Ted trades, **EXPIRED?** for past-dated expirations.
- Pricing is *lenient* (falls back to last trade on wide/absent markets) unlike the labeler's strict 50% bid-ask gate — for a position you own, a rough mark beats a blank.
- Contracts cap 100,000 (the user trades 1,800-contract spreads).

### The Ted — `/ted` (`scanner/ted_checker.py`, `api/routes/ted.py`, `TedPage.tsx`)
Earnings IV-buildup play, ported from the user's standalone CLI (`C:\Users\Apprentice\Desktop\Projects\The Ted\app.py`, checklist v1.3). Buy a single call/put 7–14 days before earnings, expiry 1–2 days past the print, **exit before earnings** — profits from IV building into the event, not the outcome.
- 14 gates in 3 sections; **10 auto-computed** from chain/greeks/fundamentals/IV history/price+sector trends. Manual: direction, contra-catalyst, BMO/AMC, analyst consensus (when FMP 402s).
- Verdicts: TRADE / CAUTION / WEAK / NO_TRADE (any hard gate fail).
- Pure gate logic is unit-tested: `backend/tests/test_ted_checker.py` (9 tests).
- **`/ted/candidates` returns empty** — FMP's earnings-calendar endpoint 402s on the user's plan tier. **Ticker search is the primary flow.**
- **Gate 02 (expiry 1–2 days past earnings) is the great filter** — most tickers fail it. JPM correctly hard-fails (Tuesday print, Friday-only expiries = 3 days).
- Requires `lxml` (yfinance `get_earnings_dates` → `pandas.read_html`).

### ML Dashboard — `/ml` (`MLDashboardPage.tsx`)
Model status, DB stats, outcome-score distribution, snapshot coverage, scan activity feed, **backtest report section** (`BacktestReportSection.tsx` ← `GET /api/v1/ml/backtest-report`, subject to §4.1 caveats), and a pipeline command reference.

### Options Chain — `/chain`
Chain viewer with sticky strike column and ATM highlighting.

### ML pipeline details
- **27 features** — the original 23 plus `is_bearish`, `vix_level`, `spy_vs_200d`, `sector_trend_20d`. `FEATURE_NAMES` is **append-only — never reorder or insert**. `model.py::_fit_width` slices inference input to an artifact's `n_features_in_`, so older artifacts keep working until the next retrain.
- **Near-miss logging** — up to 25 gate-rejected candidates per scan flagged `near_miss=1`, widening the training distribution beyond the filter boundary. Note: only Stage-8 gates (ml_score, IV rank, PoP, fundamental, sentiment); earlier filters (delta/OI/bid-ask/cost) are **not** sampled.
- **`model_version`** stamped into `features_json` from the ranker's meta `trained_at` — enables exact era segmentation.
- **Regime data** — `scanner._fetch_regime_data()`, Redis-cached 1 h; sector map in `backend/data/sector_etfs.py`.
- **Label tiers** carry trust weights (5d=0.05 … 90d=0.60 … expiry=1.00) so noisy short-horizon labels can't dominate training.

---

## 6. Operational gotchas (hard-won — each cost real debugging time)

| Gotcha | Detail |
|---|---|
| **Schwab token is read once at startup** | Re-running `schwab_auth` while the backend is live has **no effect until restart**. Symptom: bursts of `POST /oauth/token 400` a few per 150 ms (schwab-py retry storm; storms risk Schwab revoking the app). Diagnosed by comparing the port-8001 process StartTime against `creation_timestamp` inside `.schwab_token.enc`. **Always restart the backend right after re-authenticating.** |
| Schwab hardening (2026-07-28) | `schwab_client.py` now: refuses to init on a ≥7-day-old token (falls back to yfinance instead of storming); sweeps orphaned plaintext `.schwab_tmp_*` files older than 3 days (52 had accumulated since May — `atexit` never runs because start.bat force-kills); refuses to overwrite a **newer** `.enc` on shutdown (previously a stale long-running process silently reverted a fresh re-auth); hourly watchdog logs "STALE IN MEMORY — RESTART". |
| **`ML_MODEL_PATH` must be repo-relative** | It was `ml/artifacts/...`; uvicorn runs from the project root, so the trained model **silently never loaded** — the entire June era ran on placeholder scores. Fixed 2026-07-06 to `backend/ml/artifacts/...`. **Verify `/api/v1/ml/status` says `"trained"` after any restart.** |
| Schwab removed from the labeler | schwab-py retries token refresh indefinitely on 400 → multi-hour hangs. `label_outcomes` is yfinance-only. |
| Stale `frontend/dist` | The backend serves the built bundle at :8001. It was 4 months stale at one point. Run `npm run build` after UI changes, or :8001 serves an old app. Dev on :5173 is unaffected. |
| API scan id ≠ DB scan_id | The scanner generates its own uuid. Find DB rows via the "Logged N new" log line. |
| Preview stack | `.claude/launch.json` defines `leaps-backend-preview` (8004) + `leaps-frontend-preview` (5199, `--mode preview` proxying to 8004) so verification never disturbs the live 8001/5173 stack. |
| No `StandardScaler` in training | Removed 2026-07-28 — trees are scale-invariant, and it emitted `invalid value encountered in divide` warnings on all-NaN regime columns in early time-series folds. |
| SQLite lock contention | Labeling holds long write locks. Anything else touching the outcomes DB during a labeling run can stall or 500 — hence the separate presets DB. |
| FMP free tier | `/earnings-calendar`, `/price-target-consensus`, and some `/key-metrics` calls 402. Code degrades gracefully; don't treat empty results as bugs. |

---

## 7. Development history (chronological)

**Feb 2025 → Feb 2026 — greenfield build.** Backend + frontend scaffolding, scanner pipeline, tooltips, ticker modal with candlestick charts, sentiment drill-down, mobile-responsive layout, Cloudflare tunnel support with BasicAuth, delta filter. Security hardening: input validation, rate limiting, headers, and several Dependabot patch rounds (commits `020b214` … `a6bb47d`).

**Mar 2026** — universe expanded to ~587 symbols, rate-limit fixes, caching (`1c896e9`). First real ML training data begins accumulating (earliest DB entry 2026-03-12).

**Jun 2026 — ML pipeline robustness** (`5ca220a`). SQLite lock fixes (WAL, timeouts, separate transactions), `scan_events` table so the Activity feed shows every scan, the 23-vs-11 feature mismatch fixed, real HV/IV data replacing hardcoded constants, `sector_relative_strength` set to NaN, Schwab removed from the labeler, negative `days_to_earnings` suppressed, model versioning.

**Late Jun 2026 — labeling and strategy tracking.** Added `interim_45d`/`interim_60d` tiers (closing the 36–89 day gap). Built strategy outcome tracking matching the user's real rules. Trained the first strategy classifier — initially useless (AUC 0.0, 97.6% "win rate" from censoring bias).

**2026-07-05 — backtest module.** Rewrote the stub into a five-section walk-forward report using scan-time scores. First run: +39.8 decile lift, top quintile 69.4% 30-day hit rate, +$92k edge vs random.

**2026-07-06 — the placeholder-mode discovery.** Found the live backend had *never* loaded a trained model due to the relative `ML_MODEL_PATH`. Arguably the single highest-value fix of the project. Same day: Positions tracker, backtest report UI, filter persistence, FIT badge, CSV export.

**2026-07-09 — honest exit labels.** User clarified they exit at −50%, not −25%. Rewrote outcome computation as **first-passage on ±50%** and relabeled all history: losses jumped 58 → 6,707, win rate fell from a fictional 97.7% to an honest 26.8%. The classifier finally had real negatives; AUC became meaningful (0.837).

**2026-07-07 — The Ted** ported from the user's CLI into a full page + API + tests.

**2026-07-14 — data bolstering.** 27-feature schema (direction + regime), near-miss logging, `model_version` stamps, `leaps_spread_put` strategy, compat shim for old artifacts.

**2026-07-28 — Schwab incident.** Diagnosed the 400 storms (12-day-old process holding a dead token), added four layers of hardening, swept 52 leaked plaintext token files.

**2026-07-30 — era-contamination discovery + first commit in 6 weeks.** Found the backtest decile tables sort by model era rather than quality; corrected a previously-stated (wrong) trading heuristic. Committed 42 files / +4,663 lines to `feat/ted-positions-data-bolstering`, pushed. Dependency triage added.

**2026-08-03/04 — current.** Ranker v14 (MSE 240.9, best), classifier AUC 0.848.

---

## 8. Dependency security triage (2026-07-30)

GitHub reports **66 Dependabot alerts on `main`** (25 high / 36 moderate / 5 low); `main` is stale since 2026-06-18. Local audit of the current branch: **51 Python (20 packages) + 13 npm = 64** — consistent.

Reproduce:
```bash
backend\.venv\Scripts\python.exe -m pip_audit --progress-spinner off
cd frontend && npm audit                # all
cd frontend && npm audit --omit=dev     # only what ships to the browser
```

### Exposure context (read before prioritising)
- **`start.bat` launches uvicorn with `--port 8001` and NO `--host`**, so it binds **127.0.0.1 — localhost only**. `APP_HOST=0.0.0.0` in `.env` is *not used* by start.bat: misleading, currently harmless.
- `REVIEW_PASSWORD` is empty → `BasicAuthMiddleware` is **not** enabled (`main.py` adds it only when truthy).
- **If the app is ever exposed** — launched with `--host 0.0.0.0`, or fronted by the cloudflared tunnel referenced in `.gitignore` — every Tier 1 item jumps in severity and **`REVIEW_PASSWORD` must be set first**.

### Tier 1 — reachable at runtime, patch first
| Package | Now | Fix | Why it matters |
|---|---|---|---|
| `starlette` | 0.52.1 | 1.3.1 | 6 advisories; every HTTP request passes through it. **Major version jump — needs a coordinated FastAPI bump + test pass. Do NOT bump blindly.** |
| `cryptography` | 46.0.5 | 46.0.7 (48.0.1 for GHSA-537c) | 5 advisories; Fernet token encryption + TLS |
| `urllib3` | 2.6.3 | 2.7.0 | 3 advisories; all outbound HTTP (FMP / yfinance / Schwab) |
| `requests` | 2.32.5 | 2.33.0 | outbound HTTP |
| `idna` | 3.11 | 3.15 | domain parsing in the requests path |
| `curl-cffi` | 0.13.0 | 0.15.0 | yfinance's HTTP transport |
| `authlib` | 1.6.9 | 1.6.12 | 4 advisories; Schwab OAuth flow |
| `axios` (npm) | direct dep | `npm audit fix` | 3 high; ships to the browser, used by `api/client.ts` |

### Tier 2 — present but not reachable in this app
- **`python-multipart` (5)** — FastAPI form/multipart parsing. Every endpoint here is JSON; no multipart routes exist.
- **`ujson` (5)** — transitive; verified **not imported** anywhere in `backend/`.
- **`react-router` / `react-router-dom`** — open-redirect / XSS; the app has no user-supplied URLs or redirect targets.
- **`transformers` (3)** — loads one pinned public model (ProsusAI/finbert) from local cache; no untrusted model input.
- **`lodash`, `form-data`, `follow-redirects`** — transitive prod deps not used directly.

### Tier 3 — dev / build-time only (not shipped)
`vite` (high — dev-server arbitrary file read / path traversal; only while `npm run dev` is up, exploitable only by a LAN attacker or malicious page hitting localhost), `postcss`, `@babel/core`, `brace-expansion`, `picomatch`, `js-yaml`, `flatted`, `pip`, `setuptools`, `pytest`, `pygments`, `click`, `mako`, `msgpack`, `python-dotenv`, `pydantic-settings`, `soupsieve`.

**npm split: 13 total, only 6 production** (3 high / 3 moderate); the other 7 are build tooling.

### Remediation order
1. Non-breaking patches in one pass, then re-run tests:
   ```bash
   backend\.venv\Scripts\python.exe -m pip install -U cryptography urllib3 requests idna curl-cffi authlib
   cd frontend && npm audit fix
   ```
   Then `backend\.venv\Scripts\python.exe -m pytest backend/tests/ -q` and a smoke scan.
2. **Pin new versions in `backend/requirements.txt`** — otherwise a fresh venv reintroduces them.
3. starlette + FastAPI as a separate, deliberate upgrade with a full scan + Ted + positions regression pass.
4. Tier 3 whenever convenient; `vite` is the only one worth doing soon.

**Triage only — no packages upgraded.**

---

## 9. Next steps

1. **Fix `backtest.py` era segmentation** (§4.1) — highest value; makes every report section as trustworthy as the simulation already is. *Offered, awaiting user decision.*
2. **Open a PR** for `feat/ted-positions-data-bolstering` → `main`, or merge it. 6 weeks of work sits on the branch.
3. **Patch Tier 1 dependencies** (§8) — 7 non-breaking upgrades; leave starlette/FastAPI deliberate.
4. **Wait for label maturity** — the current model's first honest verdict arrives ~Oct 1 (60-day labels on July entries). Retrain weekly meanwhile; **don't over-read weekly MSE wiggles** (the 244–260 band has been noise for a month).
5. **Keep collecting bear + regime data** — unevaluable until a regime shift or ~1,000 decided bear outcomes.
6. **Deferred ideas**: EV-based ranking (expected annualized return per dollar risked), P(touch +50%) first-passage math to replace the Black-Scholes PoP, market-regime entry gate, position-sizing guidance, exit-by alerts, a "Top 10%" badge in the results table driven by a live per-model percentile cutoff.
7. **Paid historical options data** (ORATS / Polygon / CBOE DataShop, **one-time** pull ~$30–200) — the only way to obtain 2022 bear-market regime data. Do it *after* the schema settles so the backfill happens once. Backfilled rows would carry price/vol/structure features only (no historical FinBERT sentiment or point-in-time fundamentals).

---

## 10. How to use this model today (the honest version)

**It is a screening and discipline tool, not an oracle.**

**Validated:**
1. **Selection edge** — top-3-per-day picks beat random by **+$152k (+2.0σ)** in a same-day, era-safe comparison; 67.7% vs 17.5% win rate.
2. **Exit discipline** — the Positions page mechanically enforces the ±50% rules.

**Not validated:** the current model's decile rankings (§4.1, §4.2), and anything about bear or regime behavior (§4.3).

**Workflow:** scanner finds candidates → **FIT badge + highest ML scores** narrow them → human judgment picks among survivors → Positions page enforces the exit.

**Rules of interpretation:**
- Scores are **ordinal within a single model version**. Never compare raw scores across model eras — the scale has drifted from std 19.7 to std 5.9.
- The model's signal has historically lived in the **top decile only**; the middle band is noise.
- Logged P&L is **pessimistic** (§4.4) — real limit-order fills should beat it.
- Size so a drawdown stretch is survivable: the simulation's max drawdown ($83k) exceeded its profit ($50k), though it does *not* apply the −50% stop, so real-world drawdown under discipline would be smaller.
- Every backtest number to date was earned in a **bull market with no bear data in the training set**. Treat all of it as an upper bound.
