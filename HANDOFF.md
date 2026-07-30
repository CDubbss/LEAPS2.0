# Leaps2.0 — Project Handoff

> **Read this first.** Context document for an AI assistant or future maintainer.
> Every claim here was verified against the codebase / DB at the time of writing.
> **Last updated: 2026-07-30.**
>
> **Companion context files** (read alongside this):
> - `CLAUDE.md` (repo root) — how the assistant should communicate.
> - `~/.claude/projects/C--Users-Apprentice-Desktop-Projects-Leaps2-0/memory/MEMORY.md` — index of per-topic memory notes (`project_*.md`, `user_trading_strategy.md`). Those hold deeper detail on the labeling pipeline, Ted, data bolstering, and scan operations.
>
> **Verify before asserting.** This file ages. Check `spread_ranker_meta.json`, the DB, and the code before stating anything as current fact.

---

## 1. What this is

A personal options scanner + ML ranking system built around one strategy.

**Primary strategy — vertical LEAPS bull call spread**: buy lower-strike call, sell higher-strike call, **same expiration** 12+ months out.
- **25% cost rule**: net debit ≤ 25% of strike width (1:3 risk/reward).
- **Exits: +50% profit / −50% loss** (updated 2026-07-09; was −25%). Symmetric, so **breakeven win rate = 50%**.
- User's own words: *"±50% are fungible — I might exit before −50% and before +50% gains."* Thresholds model typical behavior; don't over-engineer precision.
- **Commissions**: $13 per 10-contract spread per side ($26 round trip) — baked into the target math via `_commission_adjusted_target()`.

**Secondary strategies now supported:**
- `leaps_spread_put` — bear put vertical at LEAPS DTE (added 2026-07-14 for bear-market plays).
- **"The Ted"** — earnings IV-buildup single-leg play, own page + 14-gate checklist (see §4).

### Stack
| Layer | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn — port **8001** (8000 reserved for another project) |
| Frontend | React 18 + TS + Vite (**5173**) + Tailwind dark theme, Zustand |
| Options data | yfinance (free). Schwab exists for chains but is **excluded from the labeler** (OAuth retry hazard) |
| Fundamentals | FMP (key in `backend/.env`, never commit). Free tier — several endpoints 402 |
| Sentiment | yfinance news + FinBERT (ProsusAI/finbert, CPU) |
| ML | XGBoost regressor + classifier, Optuna HPO, TimeSeriesSplit |
| Storage | SQLite `backend/ml/data/spread_outcomes.db` (WAL, ~92 MB), Redis via Docker |
| Startup | `start.bat` — backend + frontend + Redis. **Never `--reload`** (kills background scans) |

### Pipeline
1. **Scan** → 8 stages over ~587 symbols. Every candidate logged to `spread_outcomes` with a **27-feature vector**, scan-time `ml_score`, and `model_version`.
2. **Label** (`label_outcomes`, scheduled ~9 AM) → snapshots each spread's value via yfinance; tiered labels `interim_5d`…`interim_720d`/`expiry` with trust weights 0.05→1.0; computes strategy win/loss by **first-passage** on ±50%.
3. **Train** (`train.py`) → Optuna + TimeSeriesSplit → ranker (weighted MSE) + strategy classifier (AUC). Artifacts in `backend/ml/artifacts/`, 3 versioned copies kept.
4. **Backtest** (`backtest.py --json`) → validates stored scan-time scores against realized outcomes. Read-only.

**All commands must use the venv Python:**
```bash
backend\.venv\Scripts\python.exe -m backend.ml.train
```
`python -m ...` uses system Python and fails with `ModuleNotFoundError: pandas`.

---

## 2. Current state (2026-07-30)

**Models**
| Artifact | Trained | Samples | Metric |
|---|---|---|---|
| `spread_ranker.joblib` | 2026-07-30 16:56 UTC | 42,075 | Weighted MSE **244.1** (best) |
| `strategy_classifier.joblib` | 2026-07-30 17:16 UTC | 13,528 decided | AUC **0.852** (best) |

MSE trajectory: `451.6 → 455.2 → 409.2 → 408.2 → 397.3 → 368.0 → 327.8 → 257.3 → 258.3 → 259.7 → 251.2 → 259.4 → 244.1`
Classifier AUC (since honest ±50% labels): `0.837 → 0.826 → 0.815 → 0.815 → 0.852`

**Database**: 47,371 rows | 42,075 labeled | 306,559 snapshots | 1,098 near-miss | 725 bear-put (155 decided) | ~12,881 rows carry regime features.

**Strategy outcome split** (first-passage ±50%): ~25.4% win rate on decided rows.

---

## 3. ⚠️ Open issues — read before drawing conclusions

### 3.1 Backtest decile tables are era-contaminated (OPEN, highest priority)
Discovered 2026-07-30. `backtest.py` computes deciles/quintiles on **pooled** ml_scores across all model eras. But score scales drifted wildly:

| Month | mean | std |
|---|---|---|
| 2026-03 | 63.7 | **19.7** |
| 2026-06 (placeholder era) | 60.1 | **5.9** |
| 2026-07 (trained) | 53.2 | 6.7 |

Pooling std-19.7 scores with std-5.9 scores makes deciles sort largely **by era, not quality**. Verified: pooled deciles 6–9 are 57–67% June (placeholder) rows; decile 10 is 30% June + 24% April.

**Consequences:**
- The decile-lift table, quintile hit-rate table, and calibration table **cannot be read as guidance for the current model**.
- An earlier assistant conclusion ("scores 58–61 are actively worse — treat as a negative signal") was **wrong** — it was an artifact of placeholder scores clustering at 60±6. Do not repeat it.
- **The dollar simulation IS trustworthy** — it picks top-3 *within each scan day* vs random *from the same day*, so both sides always share a model era. Latest: **+$152,089 edge (+2.0σ)**, model 67.7% win rate vs random 17.5%.

**Fix not yet implemented**: segment deciles/hit-rates by `model_version` (stamps exist since ~7/14; fall back to entry-month for older rows). User was asked and had not answered when this handoff was written.

### 3.2 Current model is not yet independently validated
Trained-era-only rows (≥2026-07-08, n=13,727) exist, but **all are labeled at 5–21 days**, the tiers where rank correlation is known to be negative/noisy (`interim_10d` rho = −0.206 on 14,268 rows). Middle deciles have only 41–82 decided outcomes each — error bars too wide to conclude anything.
**The strong mature-tier correlations (90d +0.82, expiry +0.95) come from March–April entries, i.e. OLDER models.**
→ **Honest position: the current model can't be judged until its rows reach 60d+ labels, roughly September 2026.**

### 3.3 Regime + bear features unproven
12,881 rows carry VIX / SPY-vs-200d / sector-trend, but essentially all collected in **one regime** (SPY ~8% above 200d, VIX 16–17). A model can't learn regime-conditional behavior from a single regime. Bear puts: 725 rows / 155 decided, all in an uptrend. Neither is evaluable yet.

### 3.4 Entry debit is worst-case fill (by design, but misleading)
`net_debit = long_leg.ask - short_leg.bid` (`spread_constructor.py:79`), while all later snapshots mark **mid-to-mid**. Positions therefore start "underwater" by the full bid-ask cross — one observed spread showed −86% peak P&L where mid-to-mid was −62%. Fine for training (uniform penalty, teaches preference for tight markets) but **logged P&L runs pessimistic**, especially on wide markets. Real fills with limit orders should beat it.

### 3.5 `formatDate()` off-by-one
Date-only strings parsed as UTC render one day early in Mountain Time (e.g. Jan 21 → "Jan 20"). Display only — stored dates are correct. Task chip spawned, not fixed.

### 3.6 Uncommitted work (risk)
Last commit is **5ca220a (2026-06-18)**. There are **32 modified + 12 untracked files** — ~6 weeks of work (Ted, Positions, backtest UI, data bolstering, Schwab hardening) exists **only on disk**. Untracked includes `positions.py`, `ted.py`, `ted_checker.py`, `sector_etfs.py`, `TedPage.tsx`, `PositionsPage.tsx`, `BacktestReportSection.tsx`, `test_ted_checker.py`.
**Recommend committing.** Never commit `.env`, `.schwab_token.*`, or `*.db`.

---

## 4. Features built (with file pointers)

### Positions tracker — `/positions`
`backend/api/routes/positions.py`, `frontend/src/pages/PositionsPage.tsx`
Log real trades (or "Track" from a scan result); live yfinance pricing; badges **TARGET HIT — SELL** (≥ commission-adjusted +50%) / **STOP HIT** (≤ −50%) / **EXIT BY date** for Ted trades. Pricing is *lenient* (falls back to last trade on wide markets) unlike the labeler's strict 50% bid-ask gate. Contracts cap 100,000.

### The Ted — `/ted`
`backend/scanner/ted_checker.py` (pure logic, 9 unit tests), `backend/api/routes/ted.py`, `frontend/src/pages/TedPage.tsx`
Earnings IV-buildup play ported from the user's CLI (`C:\Users\Apprentice\Desktop\Projects\The Ted\app.py`, v1.3): buy single call/put 7–14 days pre-earnings, expiry 1–2 days past, **exit before the print**. 14 gates, 10 auto-computed. Verdicts TRADE / CAUTION / WEAK / NO_TRADE.
- `/ted/candidates` returns empty — FMP earnings-calendar 402s on the user's plan tier. **Ticker search is the primary flow.**
- Gate 02 (expiry 1–2 days past earnings) is the great filter; most tickers fail it.
- Needs `lxml` (yfinance `get_earnings_dates` → `pandas.read_html`).

### Backtest report UI
`GET /api/v1/ml/backtest-report` serves `artifacts/backtest_report.json`; rendered by `frontend/src/components/ml/BacktestReportSection.tsx` on the ML Dashboard. **Subject to §3.1 caveats.**

### Scanner persistence + presets
`scannerStore.ts` uses zustand `persist` (localStorage `leaps-scanner`, version 1) for filters + `activeScanId`; refresh mid-scan reattaches.
**Presets are server-side** (`backend/data/ui_presets.db` via `GET/PUT/DELETE /api/v1/scanner/presets`) — localStorage is only a warm cache. Deliberately a **separate DB** from the outcomes DB, whose labeling write-locks stalled preset reads 18–30 s / 500'd them.

### Results table
Strategy-**FIT** badge (25% cost, |delta| ≤ 0.33, OI ≥ 50, vol ≥ 10, bid-ask ≤ 25%; hover shows failures), CSV export, column sorting.

### Data bolstering (2026-07-14)
- **27 features** — appended `is_bearish`, `vix_level`, `spy_vs_200d`, `sector_trend_20d`. `FEATURE_NAMES` is **append-only; never reorder**. `model.py::_fit_width` slices inference input to an artifact's `n_features_in_` so old artifacts keep working.
- **Near-miss logging** — up to 25 gate-rejected candidates per scan flagged `near_miss=1`. Note: only Stage-8 gates (ml_score, IV rank, PoP, fundamental, sentiment); earlier filters (delta/OI/bid-ask/cost) are *not* sampled.
- **`model_version`** stamped into `features_json` from ranker meta `trained_at`.
- Regime data: `scanner._fetch_regime_data()`, Redis-cached 1 h. Sector map: `backend/data/sector_etfs.py`.

---

## 5. Operational gotchas (hard-won)

| Gotcha | Detail |
|---|---|
| **Schwab token read once at startup** | Re-running `schwab_auth` while the backend is live has **no effect until restart**. Symptom: bursts of `POST /oauth/token 400`. **Always restart after re-auth.** |
| Schwab hardening (2026-07-28) | `schwab_client.py`: refuses to init on ≥7-day-old token (avoids retry storms that risk app revocation); sweeps orphaned plaintext `.schwab_tmp_*` >3 days (52 had accumulated since May — `atexit` never runs because start.bat force-kills); won't overwrite a **newer** `.enc` on shutdown; hourly watchdog logs "STALE IN MEMORY — RESTART". |
| **`ML_MODEL_PATH` must be repo-relative** | Was `ml/artifacts/...`; uvicorn runs from project root, so the model silently never loaded → **the whole June era ran on placeholder scores**. Fixed 2026-07-06 to `backend/ml/artifacts/...`. Verify `/api/v1/ml/status` says `"trained"` after any restart. |
| Stale `frontend/dist` | Backend serves the built bundle at :8001. It was 4 months stale. Run `npm run build` after UI changes or :8001 serves an old app. Dev at :5173 is unaffected. |
| API scan id ≠ DB scan_id | The scanner generates its own uuid. Find DB rows via the "Logged N new" log line. |
| Preview stack | `.claude/launch.json` has `leaps-backend-preview` (8004) + `leaps-frontend-preview` (5199, `--mode preview`) so verification never disturbs 8001/5173. |
| No `StandardScaler` in training | Removed 2026-07-28 — trees are scale-invariant, and it emitted divide warnings on all-NaN regime columns in early time-series folds. |

---

## 6. Suggested next steps

1. **Fix `backtest.py` era segmentation** (§3.1) — makes every section as trustworthy as the simulation. Highest value.
2. **Commit the ~6 weeks of uncommitted work** (§3.6).
3. **Wait for maturity** — the current model's first honest verdict arrives when July rows hit 60d+ labels (~September). Retrain weekly meanwhile; don't over-read weekly MSE wiggles.
4. **Keep collecting bear + regime data** — both unevaluable until a regime shift or ~1,000 decided bear outcomes.
5. Deferred ideas: EV-based ranking (rank by expected annualized return per dollar risked), P(touch +50%) first-passage math to replace the Black-Scholes PoP, market-regime entry gate, position sizing guidance, exit-by alerts.
6. **Patch Tier 1 dependencies** (§7) — 7 non-breaking upgrades; leave starlette/FastAPI for a deliberate coordinated bump.
7. **Paid historical options data** (ORATS / Polygon / CBOE DataShop, one-time pull ~$30–200) — the only way to obtain 2022 bear-market regime data. Do this *after* the schema settles so the backfill only happens once. Backfilled rows would carry price/vol/structure features only (no historical FinBERT sentiment).

---

## 7. Dependency security triage (2026-07-30)

GitHub reported **66 Dependabot alerts on `main`** (25 high / 36 moderate / 5 low). `main` is stale since 2026-06-18. Local audit of the current branch found **51 Python (20 packages) + 13 npm = 64** — consistent.

Reproduce:
```bash
backend\.venv\Scripts\python.exe -m pip_audit --progress-spinner off
cd frontend && npm audit                # all
cd frontend && npm audit --omit=dev     # only what ships to the browser
```

### Exposure context (read before prioritising)
- **`start.bat` launches uvicorn with `--port 8001` and NO `--host`**, so it binds **127.0.0.1 — localhost only**. `APP_HOST=0.0.0.0` in `.env` is *not used* by start.bat: misleading, currently harmless.
- `REVIEW_PASSWORD` is empty → `BasicAuthMiddleware` is **not** enabled (`main.py` only adds it when the value is truthy).
- **If the app is ever exposed** — launched with `--host 0.0.0.0`, or fronted by the cloudflared tunnel referenced in `.gitignore` — every Tier 1 item below jumps in severity and `REVIEW_PASSWORD` should be set *first*.

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
- **`python-multipart` (5 advisories)** — FastAPI form/multipart parsing. Every endpoint here is JSON; no multipart routes exist. Not reachable.
- **`ujson` (5)** — transitive; verified **not imported** anywhere in `backend/`.
- **`react-router` / `react-router-dom` (moderate)** — open-redirect / XSS. The app has no user-supplied URLs or redirect targets.
- **`transformers` (3)** — loads one pinned public model (ProsusAI/finbert) from the local HF cache; no untrusted model input.
- **`lodash`, `form-data`, `follow-redirects`** — transitive prod deps not used directly.

### Tier 3 — dev / build-time only (not shipped, not in the running app)
`vite` (high — dev-server arbitrary file read / path traversal; only while `npm run dev` is up on 5173, and only exploitable by a LAN attacker or a malicious page hitting localhost), `postcss`, `@babel/core`, `brace-expansion`, `picomatch`, `js-yaml`, `flatted`, `pip`, `setuptools`, `pytest`, `pygments`, `click`, `mako`, `msgpack`, `python-dotenv`, `pydantic-settings`, `soupsieve`.

**npm split: 13 total, but only 6 are production** (3 high / 3 moderate) — the other 7 are build tooling.

### Suggested remediation order
1. **Non-breaking patches in one pass**, then re-run tests:
   ```bash
   backend\.venv\Scripts\python.exe -m pip install -U cryptography urllib3 requests idna curl-cffi authlib
   cd frontend && npm audit fix
   ```
   Then: `backend\.venv\Scripts\python.exe -m pytest backend/tests/ -q` and a smoke scan.
2. **Pin the new versions in `backend/requirements.txt`** — otherwise a fresh venv reintroduces them.
3. **starlette + FastAPI as a separate, deliberate upgrade** with a full scan + Ted + positions regression pass.
4. Dev-tooling (Tier 3) whenever convenient; `vite` is the only one worth doing soon.

**Not yet done** — this is triage only; no packages were upgraded.

---

## 8. How to use this model today (the honest version)

**It is a screening and discipline tool, not an oracle.**

Two things are validated:
1. **Selection edge** — top-3-per-day picks beat random by **+$152k (+2.0σ)** in a same-day, era-safe comparison, 67.7% vs 17.5% win rate.
2. **Exit discipline** — the Positions page mechanically enforces the ±50% rules humans rationalize away.

Two things are **not** validated: the current model's decile rankings (§3.1/3.2), and anything about bear or regime behavior (§3.3).

Practical workflow: scanner finds candidates → **FIT badge + highest ML scores** narrow them → human judgment picks among survivors → Positions page enforces the exit. Treat scores as **ordinal within a single model version** — never compare raw scores across model eras. Size so a drawdown stretch is survivable; the simulation's max drawdown ($83k) exceeded its profit ($50k), though it does *not* apply the −50% stop, so real-world drawdown under discipline would be smaller.
