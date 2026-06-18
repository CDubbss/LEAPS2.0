"""ML model API routes."""

import asyncio
import json
import os
import re
import sqlite3
from datetime import date, timedelta

import numpy as np

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.dependencies import get_ml_ranker
from backend.ml.model import SpreadRanker

router = APIRouter()

_DB_PATH = "backend/ml/data/spread_outcomes.db"


def _query_db_stats() -> dict:
    """Synchronous SQLite queries — called via asyncio.to_thread."""
    if not os.path.exists(_DB_PATH):
        return {
            "total": 0, "labeled": 0, "unlabeled": 0, "snapshots": 0,
            "training_threshold": 500, "ready_to_train": False,
            "recent_scans": [], "best_sell_days_distribution": [],
            "score_distribution": [], "snapshot_intervals": [],
            "avg_sell_days_by_type": [],
        }

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row

    total    = conn.execute("SELECT COUNT(*) FROM spread_outcomes").fetchone()[0]
    labeled  = conn.execute("SELECT COUNT(*) FROM spread_outcomes WHERE outcome_score IS NOT NULL").fetchone()[0]
    snapshots = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]

    # Use scan_events if available (accurate even when all candidates are duplicates).
    # Fall back to spread_outcomes for installs that don't have the table yet.
    try:
        conn.execute("SELECT 1 FROM scan_events LIMIT 1")
        recent_scans = [dict(r) for r in conn.execute("""
            SELECT entry_date AS date,
                   COUNT(*) AS scans,
                   SUM(candidates_attempted) AS candidates,
                   SUM(candidates_written) AS new_rows
            FROM scan_events
            WHERE entry_date >= DATE('now', '-14 days')
            GROUP BY entry_date
            ORDER BY entry_date DESC
        """).fetchall()]
    except Exception:
        recent_scans = [dict(r) for r in conn.execute("""
            SELECT DATE(logged_at) AS date,
                   COUNT(DISTINCT scan_id) AS scans,
                   COUNT(*) AS candidates
            FROM spread_outcomes
            WHERE logged_at >= DATE('now', '-14 days')
            GROUP BY DATE(logged_at)
            ORDER BY date DESC
        """).fetchall()]

    best_sell_dist = [dict(r) for r in conn.execute("""
        SELECT best_sell_days, COUNT(*) AS count
        FROM spread_outcomes
        WHERE best_sell_days IS NOT NULL
        GROUP BY best_sell_days
        ORDER BY best_sell_days
    """).fetchall()]

    score_dist = [dict(r) for r in conn.execute("""
        SELECT CAST(outcome_score / 10 AS INTEGER) * 10 AS bucket,
               COUNT(*) AS count
        FROM spread_outcomes
        WHERE outcome_score IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket
    """).fetchall()]

    snap_intervals = [dict(r) for r in conn.execute("""
        SELECT days_since_entry, COUNT(*) AS count
        FROM price_snapshots
        GROUP BY days_since_entry
        ORDER BY days_since_entry
    """).fetchall()]

    avg_by_type = [dict(r) for r in conn.execute("""
        SELECT spread_type,
               ROUND(AVG(best_sell_days), 1) AS avg_days,
               COUNT(*) AS count
        FROM spread_outcomes
        WHERE best_sell_days IS NOT NULL
        GROUP BY spread_type
    """).fetchall()]

    tickers_with_snapshots = [r[0] for r in conn.execute("""
        SELECT DISTINCT so.symbol
        FROM spread_outcomes so
        JOIN price_snapshots ps ON ps.outcome_id = so.id
        ORDER BY so.symbol
    """).fetchall()]

    conn.close()

    return {
        "total": total,
        "labeled": labeled,
        "unlabeled": total - labeled,
        "snapshots": snapshots,
        "training_threshold": 500,
        "ready_to_train": labeled >= 500,
        "recent_scans": recent_scans,
        "best_sell_days_distribution": best_sell_dist,
        "score_distribution": score_dist,
        "snapshot_intervals": snap_intervals,
        "avg_sell_days_by_type": avg_by_type,
        "tickers_with_snapshots": tickers_with_snapshots,
    }


def _query_score_bucket(bucket: int) -> list[dict]:
    """Return all labeled spreads in a given 10-point outcome score bucket."""
    if not os.path.exists(_DB_PATH):
        return []

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, symbol, spread_type, entry_date, expiration,
               outcome_score, peak_pnl_pct, peak_pnl_dollars,
               label_source, best_sell_days
        FROM spread_outcomes
        WHERE outcome_score IS NOT NULL
          AND CAST(outcome_score / 10 AS INTEGER) * 10 = ?
        ORDER BY peak_pnl_pct DESC
        LIMIT 200
    """, (bucket,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def _fetch_close(symbol: str, target_date: date) -> float | None:
    """
    Return the closing price of symbol on or just after target_date.
    Uses a 5-day window to bridge weekends/holidays.
    Returns None on any failure.
    """
    try:
        import yfinance as yf
        end = target_date + timedelta(days=5)
        hist = yf.Ticker(symbol).history(
            start=target_date.isoformat(),
            end=end.isoformat(),
        )
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[0]), 2)
    except Exception:
        return None


def _fetch_latest_close(symbol: str) -> float | None:
    """Return the most recent available closing price for symbol."""
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="5d")
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 2)
    except Exception:
        return None


def _query_spread_detail(spread_id: int) -> dict | None:
    """Return full contract + feature details for one spread row."""
    if not os.path.exists(_DB_PATH):
        return None

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute("""
        SELECT id, symbol, spread_type, entry_date, expiration,
               entry_net_debit, long_mid_at_entry, short_mid_at_entry, spot_at_entry,
               outcome_score, peak_pnl_pct, peak_pnl_dollars,
               label_source, best_sell_days,
               contract_json, features_json, logged_at
        FROM spread_outcomes
        WHERE id = ?
    """, (spread_id,)).fetchone()

    conn.close()

    if row is None:
        return None

    contract = json.loads(row["contract_json"] or "{}")
    features = json.loads(row["features_json"] or "{}")

    symbol      = row["symbol"]
    entry_date  = date.fromisoformat(row["entry_date"])
    best_days   = row["best_sell_days"]

    # Price at entry — already stored
    spot_at_entry = row["spot_at_entry"]

    # Price on the best sell day (entry + N business days)
    today = date.today()
    spot_at_best_day: float | None = None
    best_day_date: str | None = None
    credit_at_best_day: float | None = None   # spread value when closing at best day
    credit_today: float | None = None         # spread value if closing today (live fetch)

    if best_days is not None:
        best_date = date.fromisoformat(
            str(np.busday_offset(entry_date.isoformat(), int(best_days), roll="forward"))
        )
        best_day_date = best_date.isoformat()
        if best_date < today:
            spot_at_best_day = _fetch_close(symbol, best_date)

    # Best-day credit: pull current_value from the stored snapshot row.
    # Clamp to [0, spread_width] — negative values indicate bad yfinance mid data.
    entry_debit = row["entry_net_debit"]
    spread_width_stored = None
    if contract:
        ls = contract.get("long_strike")
        ss = contract.get("short_strike")
        if ls is not None and ss is not None:
            spread_width_stored = round(abs(float(ss) - float(ls)), 2)

    if best_days is not None:
        conn2 = sqlite3.connect(_DB_PATH)
        snap_row = conn2.execute(
            "SELECT current_value FROM price_snapshots WHERE outcome_id = ? AND days_since_entry = ?",
            (spread_id, int(best_days)),
        ).fetchone()
        conn2.close()
        if snap_row and snap_row[0] is not None:
            raw = float(snap_row[0])
            # Clamp: a spread can never be worth less than $0 or more than its width
            upper = spread_width_stored if spread_width_stored else 9999.0
            if raw >= 0:
                credit_at_best_day = round(min(raw, upper), 2)
            # If raw < 0 it's a yfinance data artefact — leave as None

    # Today's credit: live option mid fetch.
    # Recompute via label_outcomes; clamp same way.
    if contract and entry_debit:
        try:
            from backend.ml.label_outcomes import _compute_spread_value_mtm
            result = _compute_spread_value_mtm(contract, float(entry_debit))
            if result is not None:
                raw = result[0]
                upper = spread_width_stored if spread_width_stored else 9999.0
                if raw >= 0:
                    credit_today = round(min(raw, upper), 2)
        except Exception:
            pass

    # Latest available close (today or most recent trading day)
    spot_today = _fetch_latest_close(symbol)
    today_date = today.isoformat()

    def _f(key: str, digits: int = 2):
        v = features.get(key)
        return round(v, digits) if v is not None else None

    return {
        "id":            row["id"],
        "symbol":        row["symbol"],
        "spread_type":   row["spread_type"],
        "entry_date":    row["entry_date"],
        "expiration":    row["expiration"],
        "logged_at":     row["logged_at"],
        "outcome_score": row["outcome_score"],
        "peak_pnl_pct":     row["peak_pnl_pct"],
        "peak_pnl_dollars": row["peak_pnl_dollars"],
        "label_source":     row["label_source"],
        "best_sell_days":   row["best_sell_days"],
        # Entry prices
        "entry_net_debit":     row["entry_net_debit"],
        "long_mid_at_entry":   row["long_mid_at_entry"],
        "short_mid_at_entry":  row["short_mid_at_entry"],
        "spot_at_entry":       spot_at_entry,
        "spot_at_best_day":    spot_at_best_day,
        "best_day_date":       best_day_date,
        "spot_today":          spot_today,
        "today_date":          today_date,
        "credit_at_best_day":  credit_at_best_day,
        "credit_today":        credit_today,
        "spread_width":        spread_width_stored,
        # Contract legs
        "long_strike":      contract.get("long_strike"),
        "long_option_type": contract.get("long_option_type"),
        "short_strike":     contract.get("short_strike"),
        "short_option_type": contract.get("short_option_type"),
        # Greeks at entry (from features_json)
        "delta":       _f("delta", 3),
        "gamma":       _f("gamma", 4),
        "theta":       _f("theta_per_day", 4),
        "iv_rank":     _f("iv_rank", 1),
        "iv_pct":      _f("iv_percentile", 1),
        "iv_vs_hv":    _f("iv_vs_hv_ratio", 2),
        "bid_ask_pct": _f("bid_ask_spread_pct", 3),
        # Spread structure
        "dte":                    _f("dte", 0),
        "moneyness":              _f("moneyness", 3),
        "spread_width_pct":       _f("spread_width_pct", 3),
        "max_risk_reward":        _f("max_risk_reward_ratio", 2),
        "net_debit_pct_of_spread": _f("net_debit_pct_of_spread", 3),
        # Fundamentals
        "pe_ratio":        _f("pe_ratio", 1),
        "revenue_growth":  _f("revenue_growth", 3),
        "debt_to_equity":  _f("debt_to_equity", 2),
        "gross_margin":    _f("gross_margin", 3),
        "fundamental_score": _f("fundamental_score", 1),
        # Sentiment
        "sentiment_score":    _f("sentiment_score", 1),
        "sentiment_compound": _f("sentiment_compound", 3),
        # Price context
        "price_vs_52w_high": _f("price_vs_52w_high_pct", 3),
        "price_vs_52w_low":  _f("price_vs_52w_low_pct", 3),
    }


def _query_ticker_snapshot_history(symbol: str) -> dict:
    """Return all price snapshots grouped by spread entry for a single symbol."""
    if not os.path.exists(_DB_PATH):
        return {"symbol": symbol, "spreads": []}

    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
            so.id,
            so.entry_date,
            so.spread_type,
            so.entry_net_debit,
            so.spot_at_entry,
            ps.days_since_entry,
            ps.snapshot_date,
            ps.pnl_pct,
            ps.current_value
        FROM spread_outcomes so
        JOIN price_snapshots ps ON ps.outcome_id = so.id
        WHERE so.symbol = ?
        ORDER BY so.entry_date DESC, ps.days_since_entry ASC
    """, (symbol,)).fetchall()

    conn.close()

    spreads: dict[int, dict] = {}
    for row in rows:
        sid = row["id"]
        if sid not in spreads:
            spreads[sid] = {
                "id": sid,
                "entry_date": row["entry_date"],
                "spread_type": row["spread_type"],
                "entry_net_debit": row["entry_net_debit"],
                "spot_at_entry": row["spot_at_entry"],
                "snapshots": [],
            }
        spreads[sid]["snapshots"].append({
            "days_since_entry": row["days_since_entry"],
            "snapshot_date": row["snapshot_date"],
            "pnl_pct": row["pnl_pct"],
            "current_value": row["current_value"],
        })

    return {"symbol": symbol, "spreads": list(spreads.values())}


@router.get("/feature-importance", response_model=dict[str, float])
async def get_feature_importance(
    ranker: SpreadRanker = Depends(get_ml_ranker),
) -> dict[str, float]:
    """Return the ML model's feature importances for dashboard display."""
    return ranker.get_feature_importance()


@router.get("/db-stats")
async def get_ml_db_stats() -> dict:
    """Return ML training database statistics for the dashboard."""
    return await asyncio.to_thread(_query_db_stats)


@router.get("/score-bucket")
async def get_score_bucket(
    bucket: int = Query(..., ge=0, le=90, description="Lower bound of 10-point bucket (0, 10, 20 … 90)"),
) -> list[dict]:
    """Return individual spreads in a given outcome score bucket for drill-down."""
    if bucket % 10 != 0:
        raise HTTPException(status_code=422, detail="bucket must be a multiple of 10")
    return await asyncio.to_thread(_query_score_bucket, bucket)


@router.get("/spread/{spread_id}")
async def get_spread_detail(spread_id: int) -> dict:
    """Return full contract, greeks, and feature details for a single logged spread."""
    result = await asyncio.to_thread(_query_spread_detail, spread_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Spread not found")
    return result


@router.get("/ticker-snapshot-history")
async def get_ticker_snapshot_history(
    symbol: str = Query(..., min_length=1, max_length=10),
) -> dict:
    """Return per-spread P&L snapshot history for a given symbol."""
    symbol = symbol.upper().strip()
    if not re.match(r"^[A-Z0-9.\-]{1,10}$", symbol):
        raise HTTPException(status_code=422, detail="Invalid symbol format")
    return await asyncio.to_thread(_query_ticker_snapshot_history, symbol)


@router.get("/status")
async def get_ml_status(
    ranker: SpreadRanker = Depends(get_ml_ranker),
) -> dict:
    """Return ML model status (trained vs placeholder mode)."""
    return {
        "is_trained": not ranker._is_placeholder,
        "mode": "placeholder" if ranker._is_placeholder else "trained",
        "model_path": ranker.model_path,
        "message": (
            "ML model is in placeholder mode. Run scans to collect data, "
            "then train with: python -m backend.ml.train"
            if ranker._is_placeholder
            else "ML model is trained and active."
        ),
    }
