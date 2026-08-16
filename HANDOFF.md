# Leaps2.0 — Project Handoff

> **Read this first.** Full context for an AI assistant or maintainer picking this project up cold.
> Every factual claim here was verified against the codebase / database at the time of writing.
> **Last updated: 2026-08-16.**
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
   A spread is priced **atomically**: both legs from the same chain snapshot, both requiring a live two-sided quote, or the mark is discarded (§4.7). Discarded marks go to `snapshot_rejections`, never to `price_snapshots`.
3. **Train** (`train.py`) — Optuna + TimeSeriesSplit → the **ranker** (weighted-MSE regressor on 0–100 outcome scores) and the **strategy classifier** (P(hit +50% before −50%)). Artifacts to `backend/ml/artifacts/`, last 3 versions kept.
4. **Backtest** (`backtest.py --json`) — validates stored scan-time scores against realized outcomes. Read-only.

**All commands must use the venv Python:**
```bash
backend\.venv\Scripts\python.exe -m backend.ml.train
```
Plain `python -m ...` uses system Python and fails with `ModuleNotFoundError: pandas`.

---

## 3. Current state (2026-08-16)

**Models** — retrained 2026-08-15 on the market-open-only population (§4.8).
| Artifact | Trained | Samples | Metric |
|---|---|---|---|
| `spread_ranker.joblib` | 2026-08-15 09:47 UTC | 42,035 | Weighted MSE **212.4** (best) |
| `strategy_classifier.joblib` | 2026-08-15 09:50 UTC | 12,795 decided | AUC **0.873** (best) |

Progression across the data-hygiene fixes (each column is a different population):

| | original | −weekends | −holidays | **current** |
|---|---|---|---|---|
| Ranker samples | 45,364 | 39,769 | 37,846 | **42,035** |
| Ranker weighted MSE | 235.24 | 237.99 | 240.32 | **212.44** |
| Classifier samples | 14,355 | 12,470 | 11,665 | **12,795** |
| Classifier AUC | 0.8523 | 0.8630 | 0.8542 | **0.8732** |
| Classifier win rate | 25.6% | 29.3% | 29.8% | **32.5%** |

⚠️ **Weighted MSE is not comparable across these columns.** Each is a different population with a different weighted variance, and `label_outcomes` recomputes labels on every run — so an earlier run's population no longer exists and its normalised score **cannot be recovered for comparison**. The 212.4 is encouraging but is **not established as model improvement**.

The population-independent framing for the current run:

```
weighted var(y)   423.6
weighted MSE      212.4
MSE / var         0.501    ->  weighted R^2 ~= 0.50
effective n       31,983 of 42,838 rows (tier weights compress it)
```

The *win rate* is the more trustworthy trend (25.6% → 29.3% → 29.8% → **32.5%**): it is a population fact rather than a model metric, and it rose monotonically as contaminated rows were excluded.

MSE trajectory: `451.6 → … → 244.1 → 240.9 → 235.2 → 240.3 → 236.0 → 212.4*` (*populations differ; see caveat)
Classifier AUC (since the honest ±50% relabel): `0.837 → 0.826 → 0.815 → 0.815 → 0.852 → 0.848 → 0.852 → 0.854 → 0.867 → 0.873`

**Database**: 63,262 rows | 461,147 snapshots | **15,374 flagged `market_closed`** (13,348 weekend + 2,026 NYSE holiday, excluded everywhere) | 126 `expiry` ground-truth rows (**0.2%**).
**Outcome census**: `win 5,349 · loss 11,880 · open 40,113 · unlabeled 5,920` — only **27.2% decided**.
**Strategy outcome split**: **31.0%** win rate on the clean decided set. Still contaminated by legacy clamped snapshots — see §4.7.
**Snapshot quality**: **21,701 legacy boundary-pinned** rows (`clamped` with `raw_value IS NULL`) still feed labels. The collector no longer produces these; the history has not been purged.

**The market-closed guard is confirmed working in production.** Four consecutive trading days (Aug 11–14) logged 1,170 / 908 / 1,278 / 1,080 rows, all correctly unflagged; Sat Aug 15 and Sun Aug 16 logged **zero**. The `market_closed` count has not moved off 15,374 since the backfill. Aug 11–14 is also the first stretch collected under **both** atomic pair pricing (§4.7) and the market guard.

**Mature labels (60d+)**: `interim_60d` 4,418 · `interim_90d` 5,008 · `expiry` 126 — still **overwhelmingly March–May entries** (only 94 from June). See §4.2.
**Trained-era rows (≥2026-07-08)**: `interim_10d` 16,948 · `interim_21d` 5,852 · `interim_5d` 5,147 · `interim_30d` 813 — the first `interim_30d` rows have arrived, but nothing at 60d+ yet.

**Validation status** (`validate.py`, 2026-08-16): **11 PASS · 3 FAIL · 3 WARN**. Failing: H3 (decile resolution 10%–73%, score-dependent), H4b (tier/era confound), I2 (`sector_relative_strength` dead). Negative controls clean (N1 z=−0.83). Reconciliation exact (0.000%). Test suite: **32 passing**.

**Backtest** (regenerated 2026-08-16): notional-matched edge **+$104,235, p=0.0001** (z=+16.04, 10k bootstrap). The legacy 1-contract statistic the dashboard renders is **+1.04σ** — see §4.8; it has fallen 2.60 → 1.81 → 1.30 → 1.04 as contamination was removed and is now barely distinguishable from noise.

**Git**: on branch `feat/ted-positions-data-bolstering`. Working tree has uncommitted work: `validate.py`, `market_calendar.py`, the market-closed migration, and the retrained artifacts. `main` is stale since 2026-06-18. PR not yet opened.

---

## 4. ⚠️ Open issues — read before drawing conclusions

### 4.1 Backtest decile tables are era-contaminated (OPEN)
> Ranked second in §9 behind the §4.7 clamped-history purge — re-segmenting deciles is less useful while 16% of the underlying labels are still quote artifacts.
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

### 4.8 Market-closed scans logged 26% of the corpus as stale quotes (FIXED 2026-08-11)
The scheduled scan had **no market-open guard**, so it ran every Saturday, Sunday **and NYSE holiday** from 2026-03-28 onward. yfinance answers when the market is shut — it serves the **previous session's closing chain** — so those rows carry real quotes under a non-trading `entry_date`.

The quotes are genuine; the *date* is wrong by 1–2 days, and many rows are near-duplicates of a Friday row. Verified: 1,688 weekend rows carry a byte-identical `entry_net_debit` to the same contract scanned the preceding Friday (AMZN 33.25 on Fri 7/31 → 33.25 on both 8/01 and 8/02). 3,637 of 13,348 (27%) had the same contract logged the preceding weekday; the other ~9,700 are the only record of that contract.

| | |
|---|---|
| Weekend rows | 13,348 |
| NYSE holiday rows | 2,026 (Good Friday, Memorial Day, Juneteenth, July-4-observed) |
| **Combined `market_closed`** | **15,374 of 58,826 — 26.1% of the corpus** |
| Labeled | 11,308 (weekend alone) |
| Decided (win/loss) | 3,128 (weekend alone) |

**Impact on the headline number.** Duplicate rows inflate a per-scan-day top-3 simulation directly. Excluding them:

```
                                 original      -weekends    -wknd+holiday      current
legacy (1 contract, 20-iter)   $127,218 z+2.60  $89,552 z+1.81  $75,798 z+1.2  $54,033 z+1.04
notional-matched, 10k bootstrap $134,223 z+15.3 $103,625 z+15.3 $100,823 z+15.6 $104,235 z+16.0  p=0.0001
```

Roughly 40% of the published "+2.0σ" edge was market-closed rows, and the legacy statistic has kept falling as more clean data arrives: **2.60 → 1.81 → 1.30 → 1.04σ**. It is now barely distinguishable from noise. The notional-matched edge is stable across every one of those populations (z ≈ +15 to +16, p=0.0001) and the N1 negative control stays clean (z=−0.83), so the underlying selection signal is intact; the specific figure the dashboard renders is what does not survive.

**Fix — flagged, not deleted.** The quotes are real, there was no DB backup, and deletion is irreversible, so a `market_closed` column marks them and every consumer excludes them:
- **`backend/data/market_calendar.py`** — NYSE calendar built from `pandas.tseries.holiday` primitives, **no new dependency**. Deliberately *not* `USFederalHolidayCalendar`: the NYSE closes Good Friday (not federal) and trades Columbus Day and Veterans Day (both federal). Using the federal list would miss a real closure and skip two real trading days. Half sessions (day after Thanksgiving, Christmas Eve) trade normally and count as open.
- Backfilled in `label_outcomes._migrate()` — weekends in SQL via `strftime('%w')`, holidays from the Python calendar (Good Friday needs Easter, which SQL cannot compute). Idempotent. Stamped at insert by `outcome_logger`.
- Excluded in `train.py` (both loaders), `backtest.py`, and `validate.py`.
- `scheduled_scan.py` exits **before any work** when the market is closed (`--allow-market-closed` overrides, and warns). Exit 0 — a skipped non-trading day is expected, not a failure.
- Harness check **I8** recomputes closures from the calendar rather than trusting the stored flag, so a backfill that stops matching reality fails the check.
- `backend/tests/test_market_calendar.py` — 10 tests pinning the federal-vs-NYSE divergences.

*(The column was briefly named `weekend_scan`; renamed to `market_closed` when holidays were folded in, via `ALTER TABLE RENAME COLUMN` in the migration.)*

Converting this to a hard delete later remains possible; the reverse does not.

### 4.7 Clamped snapshots corrupted 16% of decided labels (COLLECTOR FIXED 2026-08-04; HISTORY NOT PURGED)
Discovered 2026-08-04 from a routine `--audit` that printed **"Data quality OK — 3.6% bad"**. The headline was hiding the problem: the audit lumped `clamped` in with `bad_data`, and `clamped` was 21,701 of the 22,341 "bad" rows.

**What `clamped` meant.** If `long_mid - short_mid` fell outside `[0, spread_width]`, the old code pinned it to the nearest boundary and stored it as a real price. That raw value is **arbitrage-impossible**, not merely odd — a negative value means the lower-strike long is quoted below the higher-strike short. Ceiling-side raw P&L ran as high as **+16,567%** before clamping.

**Root cause**: `fetch_option_mid()` priced each leg *independently*, with two independent failure modes — a per-leg `lastPrice` fallback (a trade print of unknown age, differenced against a live mid on the other leg) and a per-leg liquidity gate that never asked whether the *pair* was jointly quotable.

**Measured damage** (verified against the DB):

| | |
|---|---|
| Floor-clamped snapshots (stored as exactly −100% P&L) | 14,335 |
| Ceiling-clamped (avg +274% raw before clamp) | 7,366 |
| **Decided outcomes whose win/loss verdict was set by a clamped snapshot** | **2,288 / 14,328 = 16%** |
| — losses vs wins among those | 1,952 vs 336 |
| Spreads that hit "total loss" then later recovered above −50% | 1,432 |

`compute_strategy_outcomes()` is **first-passage** — the first snapshot to touch ±50% decides permanently, so one bad quote is irreversible, and the contamination is 6:1 skewed toward losses.

- **The classifier (AUC 0.848) is partly learning to predict data quality, not outcomes.** Clamps concentrate in wide/illiquid/stale markets, which *does* correlate with genuinely bad trades — so the confound is partly benign, but it is not what the AUC claims to measure.
- **The ranker is largely clean.** Only 4.1% of labels have a clamped peak snapshot, and mean outcome score is 51.0 (clamped) vs 50.1 (clean). MSE 240.9 stands.

**It scales with holding period** — 4.3% clamped at day 3, **13.0% at day 70**. Aged LEAPS drift from ATM and lose two-sided markets. The mature 60d/90d labels §4.2 is waiting on will be the *dirtiest* data in the set. By month fetched: Jun 9.9%, Jul 5.6%, Aug 3.8%.

**`--repair` never caught any of it.** It nulls `current_value < 0 OR pnl_pct < -100`; floor-clamped rows are *exactly* `0` and *exactly* `-100`. That is why `bad_data` is only 640.

**Fixed (collector)** — `_compute_spread_value_mtm()` now prices atomically and rejects rather than clamps. See §6 for the pricing contract.

**Not fixed (history)** — the 21,701 legacy rows are still in the DB and still feed labels. `--repair-clamped` exists and is verified in dry-run: it would null 21,701 snapshots and reset 45,218 labels + 45,344 strategy verdicts (the whole labeled set, since nulling snapshots invalidates everything derived from them). **Not run.** Before running it: let the fixed collector accumulate a few days so the new rejection rate is known — if rejections are frequent, snapshot volume drops and that is worth knowing before discarding 21k rows of history.

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

### Validation harness — `backend/ml/validate.py` (added 2026-08-06)
The adversarial "am I bullshitting myself?" audit. Read-only (`mode=ro` + `PRAGMA query_only`); **`backtest.py` is deliberately left untouched as the comparison baseline**.

```bash
backend\.venv\Scripts\python.exe -m backend.ml.validate --json      # fast sections
backend\.venv\Scripts\python.exe -m backend.ml.validate --slow      # + retraining controls
```

Thresholds are declared in a `THRESHOLDS` dict at the top of the file and printed **before** any result, so moving one after seeing a result shows up in `git diff`. Outputs a PASS/FAIL scorecard plus `validation_report.{md,json}`.

- **Section 0 — reconciliation (the gate).** Reproduces `backtest.py` on identical data to **0.000%** before any correction, then a fix-attribution ladder enables one correction at a time. If it doesn't reconcile, the reimplementation is wrong, not `backtest.py`. *(It initially missed by 4.5% — cause was tie-breaking: the June placeholder era emits ~2k distinct scores across 13k rows, and pandas `sort_values` is not stable. The model arm now uses the identical pandas idiom.)*
- **Section 1 — negative controls.** N1 shuffles `ml_score` within each scan day (must show no edge — this validates the harness itself), N2 debit-matched null, N3 permuted-label retrain, N4 injected noise feature.
- **Section 2 — honest re-measurement.** Notional-matched sizing, 10,000-iteration bootstrap p-value, business-day-aligned hit rates, resolution-safe deciles, rho by label tier.
- **Section 3 — invariants.** Row ordering, dead features, label-weight coverage, feature-contract prefix, no target feedback, report freshness, weekend-scan flagging.
- **Section 4 — doc vs reality.** Artifact claims vs recomputed DB values.

**Do not depend on `LeapsCouncil` for validation** — it is not under version control, has no `.env`, and its duplicated `FEATURE_NAMES` is 23 entries against the current 27.

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
- **Snapshot provenance** (added 2026-08-04) — every written `price_snapshots` row keeps `raw_value` (pre-clamp), `spread_width`, per-leg `bid`/`ask`/`source`/`last_trade`, and `price_provider`. `source` is `'quote'` (live two-sided) or `'last'` (trade print). `last_trade` comes from yfinance's `lastTradeDate`; it is **recorded but not yet gated on** — staleness rejection is a deliberate next step.
- **`snapshot_rejections`** — discarded marks with their raw leg quotes and a `reason` (`rejected_stale` | `rejected_bounds`). Upserts on `(outcome_id, days_since_entry)` with an `attempts` counter, so a permanently unquotable contract holds one row rather than appending daily. Surfaced by `--audit`.

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
| **Scans must not run when the market is closed** | yfinance answers when the NYSE is shut, serving the prior session's chain — real quotes, wrong `entry_date`, usually a near-duplicate. `scheduled_scan.py` exits (code 0) before any work on weekends **and NYSE holidays** via `backend/data/market_calendar.py`; `outcome_logger` stamps `market_closed=1` as a backstop. This cost 26% of the corpus and ~40% of the published edge before it was caught (§4.8). **Not modelled**: ad-hoc closures (national mourning, weather) — rare and unpredictable; the stored flag is the backstop. |
| **The spread pricing contract** | A vertical is **one instrument** and must be priced as one: both legs from the same chain snapshot, both with a live two-sided quote, or no mark at all. Violating this is what produced 21,701 corrupt snapshots (§4.7). `REQUIRE_TWO_SIDED_QUOTES = True` enforces it; flip it only to deliberately trade data quality for volume. |
| **Never write an unusable mark to `price_snapshots`** | It has `UNIQUE(outcome_id, days_since_entry)`, so a placeholder row **permanently blocks** a good snapshot at that interval. Rejections go to `snapshot_rejections` instead; leaving the interval unwritten is what preserves the retry on the next run. |
| **Clamp tolerance is absolute ($0.05), not proportional** | A bounds violation is a quote-mechanics artifact (options tick $0.01–$0.05; a mid is a half-tick; differencing two legs compounds it), so its plausible size does **not** scale with spread width. A 2%-of-width tolerance would admit a $0.20 breach on a $10 spread — real arbitrage, not rounding — and clamping that to the floor stores −100% P&L that trips the stop forever. |
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

**2026-08-06 — adversarial validation harness.** Built `backend/ml/validate.py` after the question "how do I know you aren't bullshitting me?". Verified the load-bearing claims independently; several exploration claims were **disproved** in the process (notably that cheap spreads hit +50% more often — among *decided* rows it runs the other way, <$2 → 25.5% vs $50+ → 43.1%). Headline result: the selection edge survives every correction (p=0.0001 under a 10k bootstrap with equal-risk sizing), while every *ranking* statistic — deciles, hit-rates, era comparisons — is confounded. Confirmed `HANDOFF` §4.2's position was correct; the dashboard's framing was not.

**2026-08-11 — weekend-scan discovery.** User asked to delete weekend scan data. Investigation showed the rows were **real Friday quotes with a wrong date**, not corrupt data, and amounted to 23% of the corpus with no DB backup — so they were flagged and excluded rather than deleted (§4.8). Root cause fixed in `scheduled_scan.py`. Exposed that ~30% of the published "+2.0σ" edge was weekend duplicates, dropping the legacy statistic to 1.81σ. Both models retrained on the clean 39,769-row population.

**2026-08-04 — the clamped-snapshot discovery + atomic pair pricing.** A routine `--audit` printing "Data quality OK" turned out to be hiding 21,701 boundary-pinned snapshots that had set the win/loss verdict on 16% of decided outcomes (§4.7). Root cause was per-leg independent price sourcing. Rewrote `_compute_spread_value_mtm()` as atomic pair pricing with stale/bounds rejection, added snapshot provenance columns and the `snapshot_rejections` table, fixed a lazily-initialised provider that had made the `/api/v1/ml` spread-detail live-price path silently dead, and added `--repair-clamped` for the history purge (**not yet run**). Same pattern as §4.1: a metric that looked healthy because the aggregation hid the split.

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

1. **Purge legacy clamped snapshots and re-label** (§4.7) — run `--repair-clamped` then a full labeling pass, then retrain. Do this *after* a few days of the fixed collector so the new rejection rate is known. Expect the decided win rate to move 25.4% → ~27.7% and classifier AUC to shift for real reasons; the new number is more honest, not necessarily better. *Awaiting user decision.*
2. **Fix the ML dashboard's edge figure** (§4.8) — the report is now freshly regenerated (I6 passes), but `BacktestReportSection.tsx` still reads a **static on-disk JSON with no freshness check**, and renders the 1-contract statistic — now **+1.2σ** — while never displaying the sigma, the baseline std, or the trade counts. Either regenerate on read or surface the notional-matched number with its bootstrap p-value. *The number currently shown to the user overstates the evidence.*
3. **Gate on quote staleness** (§5) — `last_trade` is already recorded on every snapshot from yfinance's `lastTradeDate`; nothing reads it yet. Rejecting quotes older than a threshold is the natural follow-on to atomic pair pricing and needs no new data.
4. **Fix `backtest.py` era segmentation** (§4.1) — makes every report section as trustworthy as the simulation already is. *Offered, awaiting user decision.*
5. **Open a PR** for `feat/ted-positions-data-bolstering` → `main`, or merge it. 6 weeks of work sits on the branch.
6. **Patch Tier 1 dependencies** (§8) — 7 non-breaking upgrades; leave starlette/FastAPI deliberate.
7. **Wait for label maturity** — the current model's first honest verdict arrives ~Oct 1 (60-day labels on July entries). Retrain weekly meanwhile; **don't over-read weekly MSE wiggles** (the 244–260 band has been noise for a month). Note §4.7: long-horizon labels are the most clamp-affected, so mature-tier counts will come in lower than previously projected once quotes are gated properly.
8. **Keep collecting bear + regime data** — unevaluable until a regime shift or ~1,000 decided bear outcomes.
9. **Deferred ideas**: EV-based ranking (expected annualized return per dollar risked), P(touch +50%) first-passage math to replace the Black-Scholes PoP, market-regime entry gate, position-sizing guidance, exit-by alerts, a "Top 10%" badge in the results table driven by a live per-model percentile cutoff.
10. **Paid historical options data** (ORATS / Polygon / CBOE DataShop, **one-time** pull ~$30–200) — the only way to obtain 2022 bear-market regime data. Do it *after* the schema settles so the backfill happens once. Backfilled rows would carry price/vol/structure features only (no historical FinBERT sentiment or point-in-time fundamentals).

---

## 10. How to use this model today (the honest version)

**It is a screening and discipline tool, not an oracle.**

**Validated:**
1. **Selection edge** — top-3-per-day picks beat random on a same-day, era-safe comparison. On the market-open-only population with **equal risk per position** and a 10,000-iteration bootstrap: **+$100,823, p=0.0001**. The older "+$152k / +2.0σ" figure used 1-contract sizing (so bet size scaled with debit, which varies 100×) and a 20-draw null; on clean data that statistic is now **+1.2σ** and no longer clears any significance bar (§4.8). Negative controls are clean — shuffling scores within a scan day gives z=−0.76.
2. **Exit discipline** — the Positions page mechanically enforces the ±50% rules.

**Not validated:** the current model's decile rankings (§4.1, §4.2), anything about bear or regime behavior (§4.3), and the classifier's AUC until the clamped history is purged (§4.7).

**Workflow:** scanner finds candidates → **FIT badge + highest ML scores** narrow them → human judgment picks among survivors → Positions page enforces the exit.

**Rules of interpretation:**
- Scores are **ordinal within a single model version**. Never compare raw scores across model eras — the scale has drifted from std 19.7 to std 5.9.
- The model's signal has historically lived in the **top decile only**; the middle band is noise.
- Logged P&L is **pessimistic** (§4.4) — real limit-order fills should beat it.
- **A "data quality OK" headline is not evidence of data quality.** Three separate problems (§4.1 era contamination, §4.7 clamped snapshots, §4.8 weekend scans) hid inside aggregates that looked healthy. When a metric pools across a quality, era, horizon, or calendar dimension, split it before trusting it.
- **Run `validate.py` before believing any number in this file.** It recomputes the headline claims independently and prints what actually reproduces. Every one of the three problems above was found by splitting an aggregate that looked fine.
- Size so a drawdown stretch is survivable: the simulation's max drawdown ($83k) exceeded its profit ($50k), though it does *not* apply the −50% stop, so real-world drawdown under discipline would be smaller.
- Every backtest number to date was earned in a **bull market with no bear data in the training set**. Treat all of it as an upper bound.
