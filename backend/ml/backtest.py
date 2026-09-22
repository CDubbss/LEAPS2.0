"""
Backtest & validation report for the SpreadRanker.

Answers the question training MSE cannot: did spreads the model scored highly
actually perform better than spreads it scored poorly?

Uses the scan-time ml_score stored in features_json (written by outcome_logger
at scan time, before the row existed in any training set) — a genuine
walk-forward, out-of-sample record.

Usage:
    python -m backend.ml.backtest                       # full report
    python -m backend.ml.backtest --since 2026-06-13    # real-model era only
    python -m backend.ml.backtest --json                # also write JSON artifact

Read-only: opens the DB with PRAGMA query_only, never writes.
"""

import argparse
import json
import logging
import random
import sqlite3
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from backend.ml.label_outcomes import _commission_adjusted_target

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "backend/ml/data/spread_outcomes.db"
REPORT_PATH = "backend/ml/artifacts/backtest_report.json"

HIT_HORIZONS = [30, 45, 60, 90]   # calendar days for time-matched hit-rate
SIM_TOP_K = 3                     # spreads taken per scan day in the simulation
SIM_BASELINE_ITERS = 20           # random-pick iterations for the baseline


# ----------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------

def load_data(db_path: str, since: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load outcomes + snapshots. Returns (outcomes_df, snapshots_df)."""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA query_only=1")
    try:
        outcomes = pd.read_sql(
            # market_closed rows are the prior session's chain stamped with a
            # non-trading entry_date; excluded so scan-day grouping reflects
            # real trading sessions.
            "SELECT id, entry_date, expiration, symbol, spread_type, "
            "       outcome_score, label_source, peak_pnl_pct, strategy_result, "
            "       days_to_target, entry_net_debit, features_json "
            "FROM spread_outcomes "
            "WHERE COALESCE(market_closed, 0) = 0 "
            "  AND spread_type NOT IN ('earnings_call', 'earnings_put')",
            conn,
        )
        snapshots = pd.read_sql(
            "SELECT outcome_id, days_since_entry, pnl_pct "
            "FROM price_snapshots WHERE pnl_pct IS NOT NULL "
            "ORDER BY outcome_id, days_since_entry",
            conn,
        )
    finally:
        conn.close()

    def extract_ml_score(fj: str) -> float:
        try:
            return float(json.loads(fj).get("ml_score", float("nan")))
        except (TypeError, ValueError, json.JSONDecodeError):
            return float("nan")

    outcomes["ml_score"] = outcomes["features_json"].map(extract_ml_score)
    outcomes = outcomes.drop(columns=["features_json"])
    outcomes = outcomes[outcomes["ml_score"].notna()].copy()

    if since:
        outcomes = outcomes[outcomes["entry_date"] >= since].copy()
        snapshots = snapshots[snapshots["outcome_id"].isin(outcomes["id"])].copy()

    outcomes["entry_month"] = outcomes["entry_date"].str[:7]
    today = date.today()
    outcomes["age_days"] = outcomes["entry_date"].map(
        lambda d: (today - date.fromisoformat(d)).days
    )
    return outcomes, snapshots


def compute_first_hit_day(outcomes: pd.DataFrame, snapshots: pd.DataFrame) -> pd.Series:
    """
    For each outcome row: first days_since_entry where snapshot P&L reached the
    commission-adjusted +50% target. NaN = never hit (so far).
    Computed from snapshots directly so it is uniform across win/loss/open rows.
    """
    thresholds = {
        row.id: _commission_adjusted_target(row.entry_net_debit)
        for row in outcomes.itertuples()
    }
    snaps = snapshots[snapshots["outcome_id"].isin(thresholds)].copy()
    snaps["threshold"] = snaps["outcome_id"].map(thresholds)
    hits = snaps[snaps["pnl_pct"] >= snaps["threshold"]]
    first_hit = hits.groupby("outcome_id")["days_since_entry"].min()
    return outcomes["id"].map(first_hit)


# ----------------------------------------------------------------------
# Section 1 + 5: decile lift and calibration
# ----------------------------------------------------------------------

def decile_analysis(labeled: pd.DataFrame) -> list[dict]:
    df = labeled.copy()
    df["decile"] = pd.qcut(df["ml_score"], 10, labels=False, duplicates="drop")
    rows = []
    for d, grp in df.groupby("decile"):
        decided = grp[grp["strategy_result"].isin(["win", "loss"])]
        rows.append({
            "decile": int(d) + 1,
            "n": len(grp),
            "ml_score_mean": round(grp["ml_score"].mean(), 1),
            "outcome_mean": round(grp["outcome_score"].mean(), 1),
            "outcome_median": round(grp["outcome_score"].median(), 1),
            "peak_pnl_mean": round(grp["peak_pnl_pct"].mean(), 1),
            "win_rate": round(len(decided[decided["strategy_result"] == "win"]) / len(decided), 3)
                        if len(decided) else None,
            "n_decided": len(decided),
        })
    return rows


def print_decile_table(rows: list[dict]) -> None:
    print("\n=== 1. DECILE LIFT (labeled rows, scan-time ml_score) ===")
    print(f"{'Dec':>3} {'N':>6} {'MLmean':>7} {'OutMean':>8} {'OutMed':>7} "
          f"{'PeakPnl%':>9} {'WinRate':>8} {'Decided':>8}")
    for r in rows:
        wr = f"{r['win_rate']:.1%}" if r["win_rate"] is not None else "-"
        print(f"{r['decile']:>3} {r['n']:>6} {r['ml_score_mean']:>7.1f} "
              f"{r['outcome_mean']:>8.1f} {r['outcome_median']:>7.1f} "
              f"{r['peak_pnl_mean']:>9.1f} {wr:>8} {r['n_decided']:>8}")
    if len(rows) >= 2:
        lift = rows[-1]["outcome_mean"] - rows[0]["outcome_mean"]
        print(f"\n  LIFT (top decile mean outcome - bottom decile): {lift:+.1f} points")


def print_calibration(rows: list[dict]) -> None:
    print("\n=== 5. CALIBRATION (predicted vs realized, per decile) ===")
    print(f"{'Dec':>3} {'Predicted':>10} {'Realized':>9} {'Gap':>7}")
    for r in rows:
        gap = r["outcome_mean"] - r["ml_score_mean"]
        print(f"{r['decile']:>3} {r['ml_score_mean']:>10.1f} "
              f"{r['outcome_mean']:>9.1f} {gap:>+7.1f}")
    print("  Gap near 0 = well calibrated; consistent sign = systematic bias.")


# ----------------------------------------------------------------------
# Section 2: rank correlation
# ----------------------------------------------------------------------

def _safe_spearman(df: pd.DataFrame) -> dict | None:
    if len(df) < 30 or df["ml_score"].nunique() < 2:
        return None
    rho, p = spearmanr(df["ml_score"], df["outcome_score"])
    return {"rho": round(float(rho), 4), "p": float(p), "n": len(df)}


def correlation_analysis(labeled: pd.DataFrame) -> dict:
    by_tier = {}
    for tier, grp in labeled.groupby("label_source"):
        s = _safe_spearman(grp)
        if s is not None:
            by_tier[tier] = s
    by_month = {}
    for month, grp in labeled.groupby("entry_month"):
        s = _safe_spearman(grp)
        if s is not None:
            by_month[month] = s
    return {"overall": _safe_spearman(labeled), "by_tier": by_tier, "by_month": by_month}


def print_correlations(corr: dict) -> None:
    print("\n=== 2. RANK CORRELATION Spearman(ml_score, outcome_score) ===")
    o = corr["overall"]
    if o:
        print(f"  Overall: rho={o['rho']:+.3f} (p={o['p']:.1e}, n={o['n']})")
    print("\n  By entry month (placeholder era = ~0 expected before ~2026-06):")
    for month in sorted(corr["by_month"]):
        s = corr["by_month"][month]
        print(f"    {month}: rho={s['rho']:+.3f} (n={s['n']})")
    print("\n  By label tier:")
    for tier in sorted(corr["by_tier"], key=lambda t: corr["by_tier"][t]["n"], reverse=True):
        s = corr["by_tier"][tier]
        print(f"    {tier:<14} rho={s['rho']:+.3f} (n={s['n']})")


# ----------------------------------------------------------------------
# Section 3: time-matched hit-rate (censoring-safe)
# ----------------------------------------------------------------------

def hit_rate_analysis(outcomes: pd.DataFrame) -> dict:
    """P(hit +50% within N days) by ml_score quintile, among rows >= N days old."""
    df = outcomes.copy()
    df["quintile"] = pd.qcut(df["ml_score"], 5, labels=False, duplicates="drop")
    result = {}
    for n in HIT_HORIZONS:
        eligible = df[df["age_days"] >= n]
        if eligible.empty:
            continue
        rows = []
        for q, grp in eligible.groupby("quintile"):
            hit = (grp["first_hit_day"] <= n).sum()
            rows.append({
                "quintile": int(q) + 1,
                "n": len(grp),
                "hit_rate": round(float(hit / len(grp)), 3),
            })
        result[str(n)] = rows
    return result


def print_hit_rates(hit: dict) -> None:
    print("\n=== 3. TIME-MATCHED HIT-RATE: P(hit +50% within N days) ===")
    print("  (only positions at least N days old; censoring-safe)")
    if not hit:
        print("  No positions old enough for any horizon yet.")
        return
    horizons = sorted(hit, key=int)
    header = f"{'Quint':>5}" + "".join(f"{'<=' + h + 'd':>10}" for h in horizons)
    print(header)
    quints = sorted({r["quintile"] for rows in hit.values() for r in rows})
    for q in quints:
        cells = ""
        for h in horizons:
            match = [r for r in hit[h] if r["quintile"] == q]
            cells += f"{match[0]['hit_rate']:>10.1%}" if match else f"{'-':>10}"
        print(f"{q:>5}{cells}")
    for h in horizons:
        ns = {r["quintile"]: r["n"] for r in hit[h]}
        print(f"  n at {h}d: {ns}")


# ----------------------------------------------------------------------
# Section 4: dollar simulation (top-K vs random-K)
# ----------------------------------------------------------------------

def _simulate(picks: pd.DataFrame, last_snap: pd.DataFrame) -> dict:
    """Simulate 1 contract per picked spread. +50% target exit, else last snapshot."""
    total_pnl, wins, days_held, unrealized = 0.0, 0, [], 0
    trades = []
    picks = picks.merge(last_snap, left_on="id", right_on="outcome_id", how="left")
    today_iso = date.today().isoformat()
    for row in picks.itertuples():
        debit = row.entry_net_debit
        if not debit or debit <= 0:
            continue
        if pd.notna(row.first_hit_day):
            pnl_pct, held, is_win = 50.0, int(row.first_hit_day), True
        elif pd.notna(row.last_pnl_pct):
            pnl_pct, held, is_win = float(row.last_pnl_pct), int(row.last_day), False
            if row.expiration >= today_iso:
                unrealized += 1
        else:
            continue  # no snapshot data at all
        pnl_dollars = (pnl_pct / 100) * debit * 100  # 1 contract = 100 shares
        total_pnl += pnl_dollars
        wins += is_win
        days_held.append(held)
        exit_ordinal = date.fromisoformat(row.entry_date).toordinal() + held
        trades.append((exit_ordinal, pnl_dollars))
    # Max drawdown on cumulative P&L ordered by exit date
    trades.sort()
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for _, pnl in trades:
        cum += pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    n = len(days_held)
    return {
        "n_trades": n,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / n, 3) if n else None,
        "avg_days_held": round(float(np.mean(days_held)), 1) if n else None,
        "max_drawdown": round(max_dd, 2),
        "unrealized_positions": unrealized,
    }


def simulation_analysis(outcomes: pd.DataFrame, snapshots: pd.DataFrame) -> dict:
    """Walk-forward: each scan day take top-K by ml_score vs random-K baseline."""
    last_snap = (
        snapshots.sort_values("days_since_entry")
        .groupby("outcome_id")
        .last()
        .reset_index()
        .rename(columns={"pnl_pct": "last_pnl_pct", "days_since_entry": "last_day"})
    )
    tradable = outcomes[
        (outcomes["entry_net_debit"] > 0)
        & outcomes["id"].isin(snapshots["outcome_id"].unique())
    ]
    top_picks = (
        tradable.sort_values("ml_score", ascending=False)
        .groupby("entry_date")
        .head(SIM_TOP_K)
    )
    top = _simulate(top_picks, last_snap)

    rng = random.Random(42)
    baseline_pnls, baseline_wr = [], []
    by_day = list(tradable.groupby("entry_date"))
    for _ in range(SIM_BASELINE_ITERS):
        parts = []
        for _, grp in by_day:
            k = min(SIM_TOP_K, len(grp))
            parts.append(grp.iloc[rng.sample(range(len(grp)), k)])
        r = _simulate(pd.concat(parts), last_snap)
        baseline_pnls.append(r["total_pnl"])
        if r["win_rate"] is not None:
            baseline_wr.append(r["win_rate"])
    baseline = {
        "iterations": SIM_BASELINE_ITERS,
        "mean_total_pnl": round(float(np.mean(baseline_pnls)), 2),
        "std_total_pnl": round(float(np.std(baseline_pnls)), 2),
        "mean_win_rate": round(float(np.mean(baseline_wr)), 3) if baseline_wr else None,
    }
    return {"top_k": SIM_TOP_K, "model": top, "random_baseline": baseline}


def print_simulation(sim: dict) -> None:
    m, b = sim["model"], sim["random_baseline"]
    print(f"\n=== 4. DOLLAR SIMULATION (top-{sim['top_k']} per scan day, "
          f"1 contract each, +50% target exit) ===")
    print(f"  Model picks:  {m['n_trades']} trades | total P&L ${m['total_pnl']:,.0f} | "
          f"win rate {m['win_rate']:.1%} | avg hold {m['avg_days_held']}d | "
          f"max DD ${m['max_drawdown']:,.0f} | {m['unrealized_positions']} still open (MTM)")
    print(f"  Random picks: mean total P&L ${b['mean_total_pnl']:,.0f} "
          f"(+/- ${b['std_total_pnl']:,.0f} over {b['iterations']} runs) | "
          f"mean win rate {b['mean_win_rate']:.1%}")
    edge = m["total_pnl"] - b["mean_total_pnl"]
    sigmas = edge / b["std_total_pnl"] if b["std_total_pnl"] else float("nan")
    print(f"  EDGE vs random: ${edge:,.0f} ({sigmas:+.1f} sigma)")
    print("  Note: open positions marked-to-market at last snapshot; "
          "a bull market lifts both columns - the edge line is what matters.")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def run(db_path: str, since: str | None, write_json: bool) -> None:
    outcomes, snapshots = load_data(db_path, since)
    outcomes["first_hit_day"] = compute_first_hit_day(outcomes, snapshots)
    labeled = outcomes[outcomes["outcome_score"].notna()]

    print("=" * 64)
    print("SPREADRANKER BACKTEST REPORT")
    print(f"  DB: {db_path}")
    print(f"  Filter: entry_date >= {since}" if since else "  Filter: none (all rows)")
    print(f"  Rows: {len(outcomes)} with ml_score | {len(labeled)} labeled | "
          f"{len(snapshots)} snapshots")
    print("=" * 64)

    deciles = decile_analysis(labeled)
    print_decile_table(deciles)

    corr = correlation_analysis(labeled)
    print_correlations(corr)

    hit = hit_rate_analysis(outcomes)
    print_hit_rates(hit)

    sim = simulation_analysis(outcomes, snapshots)
    print_simulation(sim)

    print_calibration(deciles)
    print()

    if write_json:
        report = {
            "generated_at": date.today().isoformat(),
            "db_path": db_path,
            "since": since,
            "n_rows": len(outcomes),
            "n_labeled": len(labeled),
            "decile_lift": deciles,
            "correlations": corr,
            "hit_rates": hit,
            "simulation": sim,
        }
        with open(REPORT_PATH, "w") as f:
            json.dump(report, f, indent=2)
        print(f"JSON report written to {REPORT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest the SpreadRanker against realized outcomes")
    parser.add_argument("--data-path", default=DB_PATH)
    parser.add_argument("--since", default=None, help="Only rows with entry_date >= YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="Also write JSON report artifact")
    args = parser.parse_args()
    run(args.data_path, args.since, args.json)
