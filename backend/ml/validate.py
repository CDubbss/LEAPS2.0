"""
Adversarial validation harness — the "am I bullshitting myself?" test.

Independently recomputes every headline number the project reports, using
statistics that are correct rather than convenient, and prints a PASS/FAIL
scorecard against thresholds registered BEFORE the run.

Design principles
-----------------
1. **Parallel implementation, not a patch.** backtest.py is left untouched.
   Section 0 first proves this module reproduces backtest.py on the SAME data,
   then enables each correction one at a time so every dollar of difference is
   attributable to a named fix. A reimplementation that disagrees for unknown
   reasons is worthless.

2. **Negative controls that MUST fail.** If a shuffled score produces the same
   "edge" the real model does, the pipeline is measuring an artifact. These are
   the actual bullshit tests; everything else is bookkeeping.

3. **Pre-registration is structural.** THRESHOLDS sits at the top of this file
   and is printed before any result. Moving a threshold after seeing a result
   shows up in git diff.

Read-only: opens the DB with mode=ro AND PRAGMA query_only. Never writes to
spread_outcomes.db and never mutates a model artifact.

Usage:
    python -m backend.ml.validate                     # fast sections
    python -m backend.ml.validate --slow              # + retraining controls
    python -m backend.ml.validate --section invariants
    python -m backend.ml.validate --json              # write artifacts
"""

import argparse
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "backend/ml/data/spread_outcomes.db"
LEGACY_REPORT_PATH = "backend/ml/artifacts/backtest_report.json"
RANKER_META_PATH = "backend/ml/artifacts/spread_ranker_meta.json"
CLASSIFIER_META_PATH = "backend/ml/artifacts/strategy_classifier_meta.json"
REPORT_MD = "backend/ml/artifacts/validation_report.md"
REPORT_JSON = "backend/ml/artifacts/validation_report.json"

SEED = 42

# ---------------------------------------------------------------------------
# PRE-REGISTERED THRESHOLDS — declared before the run, printed before results.
# ---------------------------------------------------------------------------

THRESHOLDS: dict[str, Any] = {
    # Section 0
    "reconcile_pnl_tolerance_pct": 0.5,     # reimplementation vs backtest.py
    # Section 1 — negative controls
    "control_max_abs_z": 2.0,               # shuffled scores must not clear this
    "control_min_p": 0.05,                  # ...and must not be significant
    "permuted_label_mse_ratio": 0.90,       # permuted-label MSE >= 90% of var(y)
    "permuted_label_auc_band": (0.45, 0.55),
    "noise_feature_max_rank": 10,           # must NOT land in top-10 importance
    # Section 2 — honest re-measurement
    "sim_min_p": 0.05,                      # notional-matched bootstrap p-value
    "holdout_max_mse_inflation": 1.50,      # holdout / reported best_weighted_mse
    "min_rho_mature_tier": 0.30,            # 60d+ tiers should clear this
    # Section 3 — invariants
    "max_feature_nan_rate": 0.999,          # a 100%-NaN feature is dead
    "report_max_age_days": 7,
}

# Equal-risk sizing for the notional-matched simulation. Every position risks
# the same dollar amount, so the comparison measures selection, not bet size.
NOTIONAL_PER_POSITION = 1_000.0

SIM_TOP_K = 3
BOOTSTRAP_ITERS = 10_000
LEGACY_BASELINE_ITERS = 20


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

PASS, FAIL, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"


@dataclass
class Check:
    id: str
    name: str
    status: str
    detail: str
    expected: str = ""


@dataclass
class Scorecard:
    checks: list[Check] = field(default_factory=list)

    def add(self, id: str, name: str, status: str, detail: str, expected: str = "") -> None:
        self.checks.append(Check(id, name, status, detail, expected))
        icon = {PASS: "[PASS]", FAIL: "[FAIL]", WARN: "[WARN]", INFO: "[INFO]"}[status]
        logger.info("  %s %-4s %s — %s", icon, id, name, detail)

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, FAIL: 0, WARN: 0, INFO: 0}
        for c in self.checks:
            out[c.status] += 1
        return out


# ---------------------------------------------------------------------------
# Data loading — INDEPENDENT of backtest.py (that is the point)
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    """Read-only connection: URI mode=ro plus query_only as belt and braces."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA query_only=1")
    return conn


def load_frames(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load outcomes + snapshots. Parses ml_score/model_version from features_json."""
    conn = _connect(db_path)
    try:
        outcomes = pd.read_sql(
            # Mirrors backtest.py's population exactly so Section 0 reconciles.
            "SELECT id, entry_date, expiration, symbol, spread_type, near_miss, "
            "       outcome_score, label_source, peak_pnl_pct, strategy_result, "
            "       days_to_target, entry_net_debit, features_json "
            "FROM spread_outcomes "
            "WHERE COALESCE(market_closed, 0) = 0 "
            "  AND spread_type NOT IN ('earnings_call', 'earnings_put')",
            conn,
        )
        snapshots = pd.read_sql(
            "SELECT outcome_id, days_since_entry, pnl_pct, data_quality "
            "FROM price_snapshots WHERE pnl_pct IS NOT NULL "
            "ORDER BY outcome_id, days_since_entry",
            conn,
        )
    finally:
        conn.close()

    def _parse(fj: str, key: str) -> Any:
        try:
            return json.loads(fj).get(key)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    outcomes["ml_score"] = outcomes["features_json"].map(
        lambda f: pd.to_numeric(_parse(f, "ml_score"), errors="coerce")
    )
    outcomes["model_version"] = outcomes["features_json"].map(
        lambda f: _parse(f, "model_version")
    )
    outcomes = outcomes.drop(columns=["features_json"])
    outcomes = outcomes[outcomes["ml_score"].notna()].copy()
    outcomes["entry_month"] = outcomes["entry_date"].str[:7]
    return outcomes, snapshots


def _last_snapshot(snapshots: pd.DataFrame) -> pd.DataFrame:
    return (
        snapshots.sort_values("days_since_entry")
        .groupby("outcome_id")
        .last()
        .reset_index()
        .rename(columns={"pnl_pct": "last_pnl_pct", "days_since_entry": "last_day"})
    )


def _first_hit(outcomes: pd.DataFrame, snapshots: pd.DataFrame) -> pd.Series:
    """First days_since_entry where P&L reached the commission-adjusted target."""
    from backend.ml.label_outcomes import _commission_adjusted_target

    thresholds = {
        row.id: _commission_adjusted_target(row.entry_net_debit)
        for row in outcomes.itertuples()
    }
    snaps = snapshots[snapshots["outcome_id"].isin(thresholds)].copy()
    snaps["threshold"] = snaps["outcome_id"].map(thresholds)
    hits = snaps[snaps["pnl_pct"] >= snaps["threshold"]]
    return outcomes["id"].map(hits.groupby("outcome_id")["days_since_entry"].min())


# ---------------------------------------------------------------------------
# Simulation core — one implementation, switchable corrections
# ---------------------------------------------------------------------------

def _tradable(outcomes: pd.DataFrame, snapshots: pd.DataFrame,
              exclude_near_miss: bool) -> pd.DataFrame:
    df = outcomes[
        (outcomes["entry_net_debit"] > 0)
        & outcomes["id"].isin(snapshots["outcome_id"].unique())
    ]
    if exclude_near_miss and "near_miss" in df.columns:
        df = df[df["near_miss"].fillna(0) != 1]
    return df


def prepare_pnl(outcomes: pd.DataFrame, snapshots: pd.DataFrame,
                exclude_near_miss: bool) -> pd.DataFrame:
    """
    Precompute each row's realized P&L ONCE.

    A row's outcome does not depend on which rows are drawn alongside it, so the
    per-row P&L is invariant across bootstrap iterations. Computing it up front
    turns each iteration from a pandas merge into numpy index arithmetic — the
    difference between 10,000 iterations being infeasible and being instant.

    Mirrors backtest.py::_simulate exit logic exactly:
      hit the target -> +50%, held = first_hit_day
      otherwise      -> last snapshot mark, held = last_day
      neither        -> dropped
    """
    last_snap = _last_snapshot(snapshots)
    t = _tradable(outcomes, snapshots, exclude_near_miss).merge(
        last_snap, left_on="id", right_on="outcome_id", how="left")

    debit = t["entry_net_debit"].to_numpy(dtype=float)
    fh = pd.to_numeric(t["first_hit_day"], errors="coerce").to_numpy(dtype=float)
    lp = pd.to_numeric(t["last_pnl_pct"], errors="coerce").to_numpy(dtype=float)
    ld = pd.to_numeric(t["last_day"], errors="coerce").to_numpy(dtype=float)

    hit = ~np.isnan(fh)
    usable = hit | ~np.isnan(lp)
    valid = (debit > 0) & usable

    pnl_pct = np.where(hit, 50.0, np.nan_to_num(lp, nan=0.0))
    held = np.where(hit, np.nan_to_num(fh, nan=0.0), np.nan_to_num(ld, nan=0.0))

    t = t.assign(
        _valid=valid,
        _is_win=hit,
        _held=held,
        _pnl_one=(pnl_pct / 100.0) * debit * 100.0,
        _pnl_notional=(pnl_pct / 100.0) * NOTIONAL_PER_POSITION,
    )
    return t[t["_valid"]].reset_index(drop=True)


def _totals(prepared: pd.DataFrame, idx: np.ndarray, sizing: str) -> float:
    col = "_pnl_one" if sizing == "one_contract" else "_pnl_notional"
    return float(prepared[col].to_numpy()[idx].sum())


def run_simulation(outcomes: pd.DataFrame, snapshots: pd.DataFrame, *,
                   sizing: str = "one_contract",
                   exclude_near_miss: bool = False,
                   iters: int = LEGACY_BASELINE_ITERS,
                   score_col: str = "ml_score",
                   debit_matched_null: bool = False,
                   prepared: Optional[pd.DataFrame] = None) -> dict:
    """Top-K per scan day vs a random-K null drawn from the same days."""
    if prepared is None:
        prepared = prepare_pnl(outcomes, snapshots, exclude_near_miss)
    if prepared.empty:
        return {"error": "no tradable rows"}

    pnl_col = "_pnl_one" if sizing == "one_contract" else "_pnl_notional"
    pnl = prepared[pnl_col].to_numpy()
    is_win = prepared["_is_win"].to_numpy()
    held = prepared["_held"].to_numpy()
    scores = prepared[score_col].to_numpy()
    debits = prepared["entry_net_debit"].to_numpy()

    groups = prepared.groupby("entry_date", sort=True).indices
    day_idx = [np.asarray(groups[d]) for d in sorted(groups)]

    # Model arm: deliberately the SAME pandas idiom as backtest.py.
    # ml_score has heavy ties (the June placeholder era emitted only ~2k distinct
    # values across 13k rows), and pandas sort_values is not stable, so a numpy
    # argsort picks different tied rows and the reconciliation drifts ~4%.
    # prepared was reset_index(drop=True), so index labels are positional.
    model_sel = (
        prepared.sort_values(score_col, ascending=False)
        .groupby("entry_date")
        .head(SIM_TOP_K)
        .index.to_numpy()
    )
    model = {
        "n_trades": int(len(model_sel)),
        "total_pnl": round(float(pnl[model_sel].sum()), 2),
        "win_rate": round(float(is_win[model_sel].mean()), 3) if len(model_sel) else None,
        "avg_days_held": round(float(held[model_sel].mean()), 1) if len(model_sel) else None,
        "median_debit": round(float(np.median(debits[model_sel])), 2) if len(model_sel) else None,
    }

    # Null arm pools. Debit-matched draws only from rows priced like the model's
    # picks that day, so "prefers cheap spreads" cannot masquerade as skill.
    pools = day_idx
    if debit_matched_null:
        model_set = set(model_sel.tolist())
        pools = []
        for d in day_idx:
            sel = np.array([i for i in d if i in model_set], dtype=int)
            if sel.size == 0:
                pools.append(d)
                continue
            lo, hi = debits[sel].min() * 0.5, debits[sel].max() * 2.0
            band = d[(debits[d] >= lo) & (debits[d] <= hi)]
            pools.append(band if len(band) >= SIM_TOP_K else d)

    rng = np.random.default_rng(SEED)
    null_totals = np.zeros(iters, dtype=float)
    for pool in pools:
        n = len(pool)
        k = min(SIM_TOP_K, n)
        if n == k:
            null_totals += pnl[pool].sum()
            continue
        # Random ranking per iteration, take the k smallest — sampling without
        # replacement, vectorised across all iterations at once.
        r = rng.random((iters, n))
        picks = np.argpartition(r, k - 1, axis=1)[:, :k]
        null_totals += pnl[pool][picks].sum(axis=1)

    edge = model["total_pnl"] - float(null_totals.mean())
    std = float(null_totals.std())
    p_value = (1 + int((null_totals >= model["total_pnl"]).sum())) / (1 + iters)

    return {
        "sizing": sizing,
        "iters": iters,
        "n_days": len(day_idx),
        "model": model,
        "null_mean": round(float(null_totals.mean()), 2),
        "null_std": round(std, 2),
        "edge": round(edge, 2),
        "z": round(edge / std, 3) if std else float("nan"),
        "p_value": round(p_value, 5),
    }


# ---------------------------------------------------------------------------
# Section 0 — Legacy reconciliation
# ---------------------------------------------------------------------------

def section_reconcile(sc: Scorecard, db_path: str,
                      outcomes: pd.DataFrame, snapshots: pd.DataFrame) -> dict:
    logger.info("\n=== SECTION 0: LEGACY RECONCILIATION ===")
    logger.info("  Proving this module reproduces backtest.py on the SAME data")
    logger.info("  before any correction is applied.\n")

    from backend.ml import backtest as legacy

    legacy_out, legacy_snaps = legacy.load_data(db_path, None)
    legacy_out["first_hit_day"] = legacy.compute_first_hit_day(legacy_out, legacy_snaps)
    legacy_sim = legacy.simulation_analysis(legacy_out, legacy_snaps)
    legacy_pnl = legacy_sim["model"]["total_pnl"]
    legacy_edge = legacy_pnl - legacy_sim["random_baseline"]["mean_total_pnl"]

    mine = run_simulation(outcomes, snapshots, sizing="one_contract",
                          exclude_near_miss=False, iters=LEGACY_BASELINE_ITERS)
    mine_pnl = mine["model"]["total_pnl"]

    denom = abs(legacy_pnl) if legacy_pnl else 1.0
    diff_pct = abs(mine_pnl - legacy_pnl) / denom * 100
    tol = THRESHOLDS["reconcile_pnl_tolerance_pct"]
    sc.add(
        "R1", "reimplementation matches backtest.py",
        PASS if diff_pct <= tol else FAIL,
        f"legacy ${legacy_pnl:,.0f} vs mine ${mine_pnl:,.0f} ({diff_pct:.3f}% apart)",
        f"<= {tol}% apart on identical data",
    )

    # Fix-attribution ladder: enable one correction at a time.
    ladder = [("legacy (1 contract, near-miss in, 20 iters)", mine)]
    step2 = run_simulation(outcomes, snapshots, sizing="one_contract",
                           exclude_near_miss=True, iters=LEGACY_BASELINE_ITERS)
    ladder.append(("+ exclude near_miss rows", step2))
    step3 = run_simulation(outcomes, snapshots, sizing="notional_matched",
                           exclude_near_miss=True, iters=LEGACY_BASELINE_ITERS)
    ladder.append(("+ notional-matched sizing", step3))
    step4 = run_simulation(outcomes, snapshots, sizing="notional_matched",
                           exclude_near_miss=True, iters=BOOTSTRAP_ITERS)
    ladder.append((f"+ {BOOTSTRAP_ITERS:,}-iter bootstrap", step4))

    logger.info("\n  Fix-attribution ladder (each row adds one correction):")
    logger.info("    %-42s %14s %9s %10s", "step", "edge", "z", "p")
    for label, r in ladder:
        logger.info("    %-42s %14s %9s %10s", label,
                    f"${r['edge']:,.0f}", f"{r['z']:+.2f}",
                    f"{r['p_value']:.4f}" if r["iters"] > 100 else "n/a")

    return {
        "legacy_backtest_pnl": legacy_pnl,
        "legacy_backtest_edge": round(legacy_edge, 2),
        "reimplementation_pnl": mine_pnl,
        "diff_pct": round(diff_pct, 4),
        "ladder": [{"step": s, **{k: v for k, v in r.items() if k != "model"}}
                   for s, r in ladder],
        "final": step4,
    }


# ---------------------------------------------------------------------------
# Section 1 — Negative controls
# ---------------------------------------------------------------------------

def section_negative_controls(sc: Scorecard, outcomes: pd.DataFrame,
                              snapshots: pd.DataFrame, slow: bool) -> dict:
    logger.info("\n=== SECTION 1: NEGATIVE CONTROLS (must show NO edge) ===")
    out: dict[str, Any] = {}

    # N1 — shuffle ml_score within each scan day. Top-K then becomes a random
    # pick from that day, so any surviving "edge" is a bug in the simulator.
    rng = np.random.default_rng(SEED)
    shuffled = outcomes.copy()
    shuffled["shuf_score"] = (
        shuffled.groupby("entry_date")["ml_score"]
        .transform(lambda s: rng.permutation(s.values))
    )
    n1 = run_simulation(shuffled, snapshots, sizing="notional_matched",
                        exclude_near_miss=True, iters=1000, score_col="shuf_score")
    ok = abs(n1["z"]) < THRESHOLDS["control_max_abs_z"] and n1["p_value"] > THRESHOLDS["control_min_p"]
    sc.add("N1", "within-day score shuffle shows no edge",
           PASS if ok else FAIL,
           f"edge ${n1['edge']:,.0f}, z={n1['z']:+.2f}, p={n1['p_value']:.4f}",
           f"|z| < {THRESHOLDS['control_max_abs_z']} and p > {THRESHOLDS['control_min_p']}")
    out["N1_within_day_shuffle"] = n1

    # N2 — debit-matched null. The model picks median $4 spreads from a pool
    # with median $16; if the edge is really a bet-size artifact it dies here.
    n2 = run_simulation(outcomes, snapshots, sizing="one_contract",
                        exclude_near_miss=True, iters=1000, debit_matched_null=True)
    out["N2_debit_matched_null"] = n2
    sc.add("N2", "edge survives a debit-matched null",
           PASS if n2["p_value"] <= THRESHOLDS["sim_min_p"] else FAIL,
           f"edge ${n2['edge']:,.0f}, z={n2['z']:+.2f}, p={n2['p_value']:.4f}",
           f"p <= {THRESHOLDS['sim_min_p']} (else the edge was bet sizing)")

    if not slow:
        sc.add("N3", "permuted-label retrain", INFO, "skipped (needs --slow)")
        sc.add("N4", "noise-feature importance", INFO, "skipped (needs --slow)")
        return out

    out.update(_slow_controls(sc))
    return out


def _slow_controls(sc: Scorecard) -> dict:
    """N3/N4 — require retraining, so they are gated behind --slow."""
    import optuna
    from xgboost import XGBRegressor

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from backend.ml.train import load_training_data

    out: dict[str, Any] = {}
    X, y, w = load_training_data(DB_PATH)

    # N3 — permute y. A model that still scores well is fitting an artifact.
    rng = np.random.default_rng(SEED)
    y_perm = rng.permutation(y)
    var_y = float(np.average((y_perm - np.average(y_perm, weights=w)) ** 2, weights=w))

    from sklearn.model_selection import TimeSeriesSplit
    tscv = TimeSeriesSplit(n_splits=3)
    scores = []
    for tr, va in tscv.split(X):
        m = XGBRegressor(n_estimators=200, max_depth=6, learning_rate=0.05,
                         random_state=SEED, tree_method="hist", device="cpu",
                         verbosity=0)
        m.fit(X[tr], y_perm[tr], sample_weight=w[tr])
        scores.append(float(np.average((m.predict(X[va]) - y_perm[va]) ** 2,
                                       weights=w[va])))
    perm_mse = float(np.mean(scores))
    ratio = perm_mse / var_y if var_y else float("nan")
    sc.add("N3", "permuted labels degrade to noise",
           PASS if ratio >= THRESHOLDS["permuted_label_mse_ratio"] else FAIL,
           f"permuted MSE {perm_mse:.1f} vs var(y) {var_y:.1f} (ratio {ratio:.2f})",
           f"ratio >= {THRESHOLDS['permuted_label_mse_ratio']}")
    out["N3_permuted_label"] = {"permuted_mse": perm_mse, "var_y": var_y,
                                "ratio": round(ratio, 4)}

    # N4 — inject pure noise as a 28th feature; it must not rank top-10.
    from backend.ml.features import FEATURE_NAMES
    X_noise = np.hstack([X, rng.normal(size=(X.shape[0], 1))])
    m = XGBRegressor(n_estimators=300, max_depth=6, learning_rate=0.05,
                     random_state=SEED, tree_method="hist", device="cpu", verbosity=0)
    m.fit(X_noise, y, sample_weight=w)
    imp = m.feature_importances_
    noise_rank = int((imp > imp[-1]).sum()) + 1
    sc.add("N4", "injected noise feature ranks low",
           PASS if noise_rank > THRESHOLDS["noise_feature_max_rank"] else FAIL,
           f"noise ranked {noise_rank} of {len(imp)} by importance",
           f"rank > {THRESHOLDS['noise_feature_max_rank']}")
    out["N4_noise_feature"] = {
        "rank": noise_rank, "n_features": len(imp),
        "top5": [FEATURE_NAMES[i] for i in np.argsort(imp)[::-1][:5]
                 if i < len(FEATURE_NAMES)],
    }
    return out


# ---------------------------------------------------------------------------
# Section 2 — Honest re-measurement
# ---------------------------------------------------------------------------

def section_honest(sc: Scorecard, outcomes: pd.DataFrame,
                   snapshots: pd.DataFrame, slow: bool) -> dict:
    logger.info("\n=== SECTION 2: HONEST RE-MEASUREMENT ===")
    out: dict[str, Any] = {}

    # H1 — notional-matched sim with a real bootstrap p-value.
    h1 = run_simulation(outcomes, snapshots, sizing="notional_matched",
                        exclude_near_miss=True, iters=BOOTSTRAP_ITERS)
    sc.add("H1", "notional-matched edge is significant",
           PASS if h1["p_value"] <= THRESHOLDS["sim_min_p"] else FAIL,
           f"edge ${h1['edge']:,.0f} on ${NOTIONAL_PER_POSITION:,.0f}/position, "
           f"p={h1['p_value']:.4f} ({BOOTSTRAP_ITERS:,} iters)",
           f"p <= {THRESHOLDS['sim_min_p']}")
    out["H1_notional_matched"] = h1

    # H2 — hit rates with both sides in business days.
    out["H2_hit_rates"] = _hit_rates_bday(outcomes, snapshots, sc)

    # H3 — decile table with 'open' left in the denominator.
    out["H3_deciles"] = _deciles_resolution_safe(outcomes, sc)

    # H4 — rho by label tier (the only non-confounded axis).
    out["H4_rho_by_tier"] = _rho_by_tier(outcomes, sc)

    if slow:
        out["H5_holdout"] = _holdout(sc)
    else:
        sc.add("H5", "true holdout vs reported metric", INFO, "skipped (needs --slow)")
    return out


def _hit_rates_bday(outcomes: pd.DataFrame, snapshots: pd.DataFrame,
                    sc: Scorecard) -> dict:
    """
    backtest.py compares calendar age_days against business-day first_hit_day.
    Both sides are business days here, using label_outcomes' own helper.
    """
    from backend.ml.label_outcomes import _bdays_elapsed

    df = outcomes.copy()
    today = date.today()
    df["age_bdays"] = df["entry_date"].map(
        lambda d: _bdays_elapsed(date.fromisoformat(d), today)
    )
    df["age_cdays"] = df["entry_date"].map(
        lambda d: (today - date.fromisoformat(d)).days
    )
    df["quintile"] = pd.qcut(df["ml_score"], 5, labels=False, duplicates="drop")

    result = {}
    for n in (30, 45, 60, 90):
        elig_b = df[df["age_bdays"] >= n]
        elig_c = df[df["age_cdays"] >= n]
        if elig_b.empty:
            continue
        rows = []
        for q, grp in elig_b.groupby("quintile"):
            hit = (grp["first_hit_day"] <= n).sum()
            rows.append({"quintile": int(q) + 1, "n": len(grp),
                         "hit_rate": round(float(hit / len(grp)), 3)})
        result[str(n)] = {
            "rows": rows,
            "n_eligible_bday": len(elig_b),
            "n_eligible_calendar": len(elig_c),
        }

    if result:
        h = sorted(result, key=int)[0]
        nb, nc = result[h]["n_eligible_bday"], result[h]["n_eligible_calendar"]
        inflate = (nc - nb) / nb * 100 if nb else float("nan")
        sc.add("H2", "hit-rate denominator (bday vs calendar)", WARN,
               f"at {h}d: {nb} eligible on business days vs {nc} on calendar "
               f"(legacy over-counts by {inflate:.0f}%)",
               "same unit on both sides")
    return result


def _deciles_resolution_safe(outcomes: pd.DataFrame, sc: Scorecard) -> list[dict]:
    """Win rate over ALL rows in the decile, not just resolved ones."""
    labeled = outcomes[outcomes["outcome_score"].notna()].copy()
    if labeled.empty:
        return []
    labeled["decile"] = pd.qcut(labeled["ml_score"], 10, labels=False, duplicates="drop")
    rows = []
    for d, grp in labeled.groupby("decile"):
        decided = grp[grp["strategy_result"].isin(["win", "loss"])]
        n_win = int((grp["strategy_result"] == "win").sum())
        rows.append({
            "decile": int(d) + 1,
            "n": len(grp),
            "n_decided": len(decided),
            "pct_resolved": round(100 * len(decided) / len(grp), 1),
            "win_rate_legacy": round(n_win / len(decided), 3) if len(decided) else None,
            "win_rate_all_rows": round(n_win / len(grp), 3),
        })
    if rows:
        res = [r["pct_resolved"] for r in rows]
        sc.add("H3", "decile resolution rate is score-dependent",
               FAIL if max(res) - min(res) > 20 else PASS,
               f"resolved% ranges {min(res):.0f}%-{max(res):.0f}% across deciles",
               "flat resolution (else win_rate is outcome-conditioned)")
    return rows


def _rho_by_tier(outcomes: pd.DataFrame, sc: Scorecard) -> dict:
    labeled = outcomes[outcomes["outcome_score"].notna()]
    out = {}
    for tier, grp in labeled.groupby("label_source"):
        if len(grp) < 40 or grp["ml_score"].nunique() < 2:
            continue
        rho, p = spearmanr(grp["ml_score"], grp["outcome_score"])
        months = sorted(grp["entry_month"].unique())
        out[tier] = {"rho": round(float(rho), 4), "p": float(p), "n": len(grp),
                     "months": months, "n_months": len(months)}

    mature = {t: v for t, v in out.items()
              if t in ("interim_60d", "interim_90d", "interim_180d", "expiry")}
    if mature:
        best = max(mature.values(), key=lambda v: v["rho"])
        sc.add("H4", "mature-tier rank correlation",
               PASS if best["rho"] >= THRESHOLDS["min_rho_mature_tier"] else FAIL,
               f"best mature tier rho={best['rho']:+.3f} (n={best['n']})",
               f"rho >= {THRESHOLDS['min_rho_mature_tier']}")

    # The confound that makes every era comparison uninterpretable.
    single = [t for t, v in out.items() if v["n_months"] <= 2]
    sc.add("H4b", "label tier vs entry month confound",
           FAIL if len(single) >= len(out) * 0.6 else PASS,
           f"{len(single)}/{len(out)} tiers span <=2 entry months "
           f"— era and horizon cannot be separated",
           "tiers spread across many months")
    return out


def _holdout(sc: Scorecard) -> dict:
    """Train on the first 80% by entry_date, score once on the last 20%."""
    import optuna
    from sklearn.model_selection import TimeSeriesSplit
    from xgboost import XGBRegressor

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    conn = _connect(DB_PATH)
    try:
        df = pd.read_sql(
            "SELECT features_json, outcome_score, label_source, entry_date "
            "FROM spread_outcomes "
            "WHERE outcome_score IS NOT NULL "
            "  AND COALESCE(market_closed, 0) = 0 "
            "  AND spread_type NOT IN ('earnings_call','earnings_put') "
            "ORDER BY entry_date, id",
            conn,
        )
    finally:
        conn.close()

    from backend.ml.features import FEATURE_NAMES
    from backend.ml.train import LABEL_WEIGHTS

    X, y, w = [], [], []
    for _, r in df.iterrows():
        f = json.loads(r["features_json"])
        X.append([f.get(n, float("nan")) for n in FEATURE_NAMES])
        y.append(float(r["outcome_score"]))
        w.append(LABEL_WEIGHTS.get(r["label_source"] or "expiry", 1.0))
    X, y, w = np.array(X, float), np.array(y, float), np.array(w, float)

    cut = int(len(X) * 0.8)
    Xtr, Xte, ytr, yte, wtr, wte = X[:cut], X[cut:], y[:cut], y[cut:], w[:cut], w[cut:]

    def objective(trial):
        p = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "random_state": SEED, "tree_method": "hist", "device": "cpu",
        }
        s = []
        for tr, va in TimeSeriesSplit(n_splits=3).split(Xtr):
            m = XGBRegressor(**p, verbosity=0)
            m.fit(Xtr[tr], ytr[tr], sample_weight=wtr[tr])
            s.append(float(np.average((m.predict(Xtr[va]) - ytr[va]) ** 2,
                                      weights=wtr[va])))
        return float(np.mean(s))

    study = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=SEED))
    study.optimize(objective, n_trials=15, show_progress_bar=False)

    best = dict(study.best_params)
    best.update({"random_state": SEED, "tree_method": "hist", "device": "cpu"})
    final = XGBRegressor(**best, verbosity=0)
    final.fit(Xtr, ytr, sample_weight=wtr)
    holdout_mse = float(np.average((final.predict(Xte) - yte) ** 2, weights=wte))

    reported = None
    if os.path.exists(RANKER_META_PATH):
        with open(RANKER_META_PATH) as f:
            reported = json.load(f).get("best_weighted_mse")

    ratio = holdout_mse / reported if reported else float("nan")

    # A weighted MSE is only comparable across populations with the same
    # weighted variance. Recent rows carry short-horizon tiers (weight 0.05-0.20)
    # with a much tighter outcome spread, so a "better" holdout number can mean
    # an easier population rather than an unbiased model. Report both.
    def _wvar(yy, ww):
        return float(np.average((yy - np.average(yy, weights=ww)) ** 2, weights=ww))

    var_tr, var_te = _wvar(ytr, wtr), _wvar(yte, wte)
    tiers_te = df.iloc[cut:]["label_source"].value_counts().head(3).to_dict()
    comparable = 0.7 <= (var_te / var_tr if var_tr else 0) <= 1.43

    if not comparable:
        status, note = WARN, (
            f"holdout MSE {holdout_mse:.1f} vs reported {reported:.1f} (x{ratio:.2f}) "
            f"BUT populations differ: weighted var(y) train {var_tr:.0f} vs "
            f"holdout {var_te:.0f} — ratio is not a clean HPO-inflation measure. "
            f"Holdout tiers: {tiers_te}"
        )
    else:
        status = PASS if ratio <= THRESHOLDS["holdout_max_mse_inflation"] else FAIL
        note = (f"holdout MSE {holdout_mse:.1f} vs reported {reported:.1f} "
                f"(x{ratio:.2f}); weighted var(y) comparable "
                f"({var_tr:.0f} vs {var_te:.0f})")

    sc.add("H5", "true holdout vs reported best_weighted_mse", status, note,
           f"ratio <= {THRESHOLDS['holdout_max_mse_inflation']} on a comparable population")
    return {"holdout_weighted_mse": round(holdout_mse, 2),
            "reported_best_weighted_mse": reported,
            "inflation_ratio": round(ratio, 4) if reported else None,
            "cv_best_on_train": round(study.best_value, 2),
            "weighted_var_train": round(var_tr, 2),
            "weighted_var_holdout": round(var_te, 2),
            "holdout_tier_mix": tiers_te,
            "populations_comparable": comparable,
            "n_train": int(cut), "n_holdout": int(len(X) - cut)}


# ---------------------------------------------------------------------------
# Section 3 — Invariants
# ---------------------------------------------------------------------------

def section_invariants(sc: Scorecard, db_path: str) -> dict:
    logger.info("\n=== SECTION 3: INVARIANTS ===")
    out: dict[str, Any] = {}

    # I1 — training row order must be chronological (TimeSeriesSplit depends on it)
    conn = _connect(db_path)
    try:
        dates = [r[0] for r in conn.execute(
            "SELECT entry_date FROM spread_outcomes "
            "WHERE outcome_score IS NOT NULL "
            "  AND COALESCE(market_closed, 0) = 0 "
            "  AND spread_type NOT IN ('earnings_call','earnings_put')"
        )]
        closed_total = conn.execute(
            "SELECT COUNT(*) FROM spread_outcomes WHERE COALESCE(market_closed,0)=1"
        ).fetchone()[0]
        # Recompute independently from the NYSE calendar rather than trusting
        # the stored flag — the point of the check is to catch a backfill that
        # silently stopped matching reality.
        open_dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT entry_date FROM spread_outcomes "
            "WHERE COALESCE(market_closed,0)=0 AND entry_date IS NOT NULL"
        )]
        # Sample the MOST RECENT rows. Features added later (the 2026-07 regime
        # block) are legitimately absent from old rows, so judging "dead" on the
        # oldest rows would condemn every recently-added feature.
        feats = [r[0] for r in conn.execute(
            "SELECT features_json FROM spread_outcomes "
            "WHERE features_json IS NOT NULL ORDER BY id DESC LIMIT 20000"
        )]
        feats_old = [r[0] for r in conn.execute(
            "SELECT features_json FROM spread_outcomes "
            "WHERE features_json IS NOT NULL ORDER BY id ASC LIMIT 5000"
        )]
        label_sources = [r[0] for r in conn.execute(
            "SELECT DISTINCT label_source FROM spread_outcomes "
            "WHERE label_source IS NOT NULL"
        )]
        census = dict(conn.execute(
            "SELECT COALESCE(strategy_result,'NULL'), COUNT(*) "
            "FROM spread_outcomes GROUP BY 1"
        ).fetchall())
        n_expiry = conn.execute(
            "SELECT COUNT(*) FROM spread_outcomes WHERE label_source='expiry'"
        ).fetchone()[0]
        max_entry = conn.execute(
            "SELECT MAX(entry_date) FROM spread_outcomes"
        ).fetchone()[0]
    finally:
        conn.close()

    inversions = sum(1 for a, b in zip(dates, dates[1:]) if b < a)
    sc.add("I1", "training rows are chronologically ordered",
           PASS if inversions == 0 else FAIL,
           f"{inversions:,} order inversions in {len(dates):,} rows "
           f"(TimeSeriesSplit assumes none)",
           "0 inversions — add ORDER BY entry_date")
    out["I1_order_inversions"] = inversions

    # I2 — dead features
    from backend.ml.features import FEATURE_NAMES

    def _parse_all(rows: list[str]) -> list[dict]:
        got = []
        for fj in rows:
            try:
                got.append(json.loads(fj))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return got

    recent, old = _parse_all(feats), _parse_all(feats_old)

    def _stat(parsed: list[dict], name: str) -> tuple[float, float]:
        vals = pd.to_numeric(pd.Series([p.get(name) for p in parsed]), errors="coerce")
        return (float(vals.isna().mean()),
                float(vals.std()) if vals.notna().any() else 0.0)

    dead, newer, stats = [], [], {}
    for name in FEATURE_NAMES:
        nan_r, std_r = _stat(recent, name)
        nan_o, std_o = _stat(old, name)
        stats[name] = {"recent_nan_rate": round(nan_r, 4), "recent_std": round(std_r, 6),
                       "oldest_nan_rate": round(nan_o, 4), "oldest_std": round(std_o, 6)}
        is_dead_now = nan_r >= THRESHOLDS["max_feature_nan_rate"] or std_r == 0.0
        if is_dead_now:
            dead.append(name)
        elif nan_o >= THRESHOLDS["max_feature_nan_rate"]:
            newer.append(name)  # legitimately absent from old rows, alive now

    sc.add("I2", "no dead (constant / all-NaN) features",
           PASS if not dead else FAIL,
           f"{len(dead)} dead of {len(FEATURE_NAMES)} in the newest 20k rows: "
           f"{', '.join(dead) or 'none'}",
           "0 dead features")
    if newer:
        sc.add("I2b", "features absent from early training rows", WARN,
               f"{len(newer)} alive now but ~100% NaN in the oldest rows: "
               f"{', '.join(newer)} — XGBoost can learn missingness as a date proxy",
               "informational: early folds train a narrower model")
    out["I2_feature_stats"] = stats
    out["I2_dead_features"] = dead
    out["I2_recently_added"] = newer

    # I3 — every label tier has an explicit weight
    from backend.ml.train import LABEL_WEIGHTS
    unknown = [s for s in label_sources if s not in LABEL_WEIGHTS]
    sc.add("I3", "all label tiers have explicit weights",
           PASS if not unknown else FAIL,
           f"unknown tiers: {unknown or 'none'} "
           f"(.get default 1.0 grants them FULL trust)",
           "every tier in LABEL_WEIGHTS")
    out["I3_unknown_tiers"] = unknown

    # I4 — artifact feature list must be a prefix of the current contract
    art = None
    if os.path.exists(RANKER_META_PATH):
        with open(RANKER_META_PATH) as f:
            art = json.load(f).get("feature_names")
    if art:
        is_prefix = list(FEATURE_NAMES[:len(art)]) == list(art)
        sc.add("I4", "artifact features are a prefix of FEATURE_NAMES",
               PASS if is_prefix else FAIL,
               f"artifact has {len(art)}, current contract has {len(FEATURE_NAMES)}, "
               f"prefix={is_prefix}",
               "append-only contract holds")
        out["I4_prefix_ok"] = is_prefix

    # I5 — no target feedback into the feature set
    forbidden = {"ml_score", "model_version", "net_debit", "max_profit", "max_loss",
                 "outcome_score", "peak_pnl_pct"}
    overlap = forbidden & set(FEATURE_NAMES)
    sc.add("I5", "no target/outcome fields used as features",
           PASS if not overlap else FAIL,
           f"overlap: {overlap or 'none'}",
           "empty intersection")

    # I6 — stale published report
    if os.path.exists(LEGACY_REPORT_PATH):
        with open(LEGACY_REPORT_PATH) as f:
            gen = json.load(f).get("generated_at")
        age = (date.today() - date.fromisoformat(gen)).days if gen else None
        sc.add("I6", "published backtest report is fresh",
               PASS if age is not None and age <= THRESHOLDS["report_max_age_days"] else FAIL,
               f"generated {gen}, {age}d old; newest DB entry {max_entry} "
               f"(API serves this as live)",
               f"<= {THRESHOLDS['report_max_age_days']}d old")
        out["I6_report_age_days"] = age

    # I8 — market-closed rows must all be flagged, and none may reach training.
    # Options do not trade Sat/Sun, so those scans record Friday's closing chain
    # under a non-trading entry_date: real quotes, wrong date, often a
    # near-duplicate of the prior session.
    from backend.data.market_calendar import market_closed_reason

    leaks: dict[str, int] = {}
    for ds in open_dates:
        try:
            reason = market_closed_reason(date.fromisoformat(ds))
        except ValueError:
            continue
        if reason:
            leaks[reason] = leaks.get(reason, 0) + 1
    n_leak_dates = sum(leaks.values())

    sc.add("I8", "market-closed rows are flagged and excluded",
           PASS if n_leak_dates == 0 else FAIL,
           f"{closed_total:,} flagged; {n_leak_dates} unflagged non-trading "
           f"date(s) {leaks or ''} would leak into training",
           "0 unflagged — run label_outcomes to backfill")
    out["I8_market_closed"] = {"flagged": closed_total,
                               "unflagged_dates": leaks}

    # I7 — census, for context on every other number
    decided = census.get("win", 0) + census.get("loss", 0)
    total = sum(census.values())
    sc.add("I7", "outcome census", INFO,
           f"{census} | decided {decided:,}/{total:,} "
           f"({100*decided/total:.1f}%) | ground-truth expiry rows {n_expiry}")
    out["I7_census"] = {"strategy_result": census, "n_expiry_rows": n_expiry,
                        "max_entry_date": max_entry}
    return out


# ---------------------------------------------------------------------------
# Section 4 — Doc vs reality
# ---------------------------------------------------------------------------

def section_doc_vs_reality(sc: Scorecard, recon: dict, inv: dict) -> dict:
    logger.info("\n=== SECTION 4: DOC vs REALITY (HANDOFF.md claims) ===")
    out: dict[str, Any] = {}

    claims = []
    for path, keys in ((RANKER_META_PATH, ("best_weighted_mse", "n_samples")),
                       (CLASSIFIER_META_PATH, ("best_auc", "n_samples", "win_rate"))):
        if os.path.exists(path):
            with open(path) as f:
                meta = json.load(f)
            for k in keys:
                claims.append((os.path.basename(path), k, meta.get(k)))
    out["artifact_claims"] = [{"file": f, "key": k, "value": v} for f, k, v in claims]
    for f, k, v in claims:
        logger.info("    %-32s %-22s %s", f, k, v)

    census = inv.get("I7_census", {}).get("strategy_result", {})
    decided = census.get("win", 0) + census.get("loss", 0)
    actual_wr = census.get("win", 0) / decided if decided else float("nan")
    out["recomputed_win_rate"] = round(actual_wr, 4)

    legacy_edge = recon.get("legacy_backtest_edge")
    final = recon.get("final", {})
    sc.add("D1", "headline edge survives correction",
           WARN,
           f"published (1-contract, 20-iter) ${legacy_edge:,.0f} -> "
           f"corrected ${final.get('edge', float('nan')):,.0f} "
           f"(p={final.get('p_value')}) — different units, not comparable directly",
           "see Section 0 ladder for attribution")

    sc.add("D2", "win rate reproducible from DB", INFO,
           f"recomputed decided win rate {actual_wr:.1%} "
           f"(HANDOFF quotes ~25.4%, contaminated per §4.7)")
    return out


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------

def write_reports(sc: Scorecard, payload: dict) -> None:
    os.makedirs(os.path.dirname(REPORT_JSON), exist_ok=True)
    with open(REPORT_JSON, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    counts = sc.counts()
    lines = [
        "# Validation Report",
        "",
        f"Generated: {payload['generated_at']}",
        f"DB: `{payload['db_path']}`",
        "",
        f"**{counts[PASS]} pass · {counts[FAIL]} fail · "
        f"{counts[WARN]} warn · {counts[INFO]} info**",
        "",
        "## Pre-registered thresholds",
        "",
        "```json",
        json.dumps(THRESHOLDS, indent=2),
        "```",
        "",
        "## Scorecard",
        "",
        "| ID | Check | Status | Detail | Expected |",
        "|---|---|---|---|---|",
    ]
    for c in sc.checks:
        detail = c.detail.replace("|", "\\|")
        lines.append(f"| {c.id} | {c.name} | **{c.status}** | {detail} | {c.expected} |")
    lines += ["", "## Raw results", "", "```json",
              json.dumps(payload.get("sections", {}), indent=2, default=str)[:20000],
              "```", ""]
    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(db_path: str, slow: bool, section: Optional[str], write: bool) -> int:
    sc = Scorecard()
    logger.info("=" * 72)
    logger.info("ADVERSARIAL VALIDATION HARNESS")
    logger.info("  DB: %s", db_path)
    logger.info("  Mode: %s", "full (--slow)" if slow else "fast")
    logger.info("=" * 72)
    logger.info("\nPRE-REGISTERED THRESHOLDS (declared before results):")
    for k, v in THRESHOLDS.items():
        logger.info("    %-34s %s", k, v)

    outcomes, snapshots = load_frames(db_path)
    outcomes["first_hit_day"] = _first_hit(outcomes, snapshots)
    logger.info("\n  Loaded %s rows with ml_score, %s snapshots",
                f"{len(outcomes):,}", f"{len(snapshots):,}")

    sections: dict[str, Any] = {}
    want = lambda s: section is None or section == s  # noqa: E731

    recon: dict = {}
    if want("reconcile"):
        recon = section_reconcile(sc, db_path, outcomes, snapshots)
        sections["reconcile"] = recon
    if want("negative-controls"):
        sections["negative_controls"] = section_negative_controls(
            sc, outcomes, snapshots, slow)
    if want("honest"):
        sections["honest"] = section_honest(sc, outcomes, snapshots, slow)
    inv: dict = {}
    if want("invariants"):
        inv = section_invariants(sc, db_path)
        sections["invariants"] = inv
    if want("doc") and recon and inv:
        sections["doc_vs_reality"] = section_doc_vs_reality(sc, recon, inv)

    counts = sc.counts()
    logger.info("\n" + "=" * 72)
    logger.info("SCORECARD: %d PASS · %d FAIL · %d WARN · %d INFO",
                counts[PASS], counts[FAIL], counts[WARN], counts[INFO])
    if counts[FAIL]:
        logger.info("\nFailures:")
        for c in sc.checks:
            if c.status == FAIL:
                logger.info("  %-4s %s", c.id, c.name)
                logger.info("       got:      %s", c.detail)
                logger.info("       expected: %s", c.expected)
    logger.info("=" * 72)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": db_path,
        "slow": slow,
        "thresholds": THRESHOLDS,
        "scorecard": [c.__dict__ for c in sc.checks],
        "counts": counts,
        "sections": sections,
    }
    if write:
        write_reports(sc, payload)
        logger.info("Wrote %s and %s", REPORT_MD, REPORT_JSON)
    return counts[FAIL]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Adversarial validation of the ML pipeline")
    ap.add_argument("--db-path", default=DB_PATH)
    ap.add_argument("--slow", action="store_true",
                    help="Include retraining controls (N3/N4/H5)")
    ap.add_argument("--section",
                    choices=["reconcile", "negative-controls", "honest",
                             "invariants", "doc"])
    ap.add_argument("--json", action="store_true", help="Write report artifacts")
    args = ap.parse_args()
    raise SystemExit(0 if run(args.db_path, args.slow, args.section, args.json) == 0 else 1)
