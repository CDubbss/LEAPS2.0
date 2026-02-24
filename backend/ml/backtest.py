"""
Simple walk-forward backtesting for spread recommendations.
Simulates running the scanner weekly and checking outcomes at expiry.

Usage:
    python -m backend.ml.backtest --start 2024-01-01 --end 2024-06-01
"""

import argparse
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    symbol: str
    spread_type: str
    expiration: str
    entry_date: str
    net_debit: float
    max_profit: float
    max_loss: float
    ml_score: float
    outcome_score: Optional[float] = None  # set after expiry
    pnl_pct: Optional[float] = None


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_winner_pct: float
    avg_loser_pct: float
    total_return_pct: float
    max_drawdown_pct: float
    ml_score_correlation: float  # correlation between ML score and actual PnL
    summary: str


def run_backtest(db_path: str, start_date: str, end_date: str) -> BacktestResult:
    """
    Load historical spread outcomes from database and compute backtest metrics.
    Assumes outcome_score and pnl fields have been populated after expiry.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("""
            SELECT symbol, spread_type, expiration, entry_date,
                   features_json, outcome_score
            FROM spread_outcomes
            WHERE entry_date >= ? AND entry_date <= ?
              AND outcome_score IS NOT NULL
            ORDER BY entry_date
        """, (start_date, end_date)).fetchall()
    finally:
        conn.close()

    if not rows:
        logger.warning("No labeled outcomes found for period %s to %s", start_date, end_date)
        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            avg_winner_pct=0.0,
            avg_loser_pct=0.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            ml_score_correlation=0.0,
            summary="No labeled data available for this period.",
        )

    trades = []
    for row in rows:
        features = json.loads(row[4])
        trade = BacktestTrade(
            symbol=row[0],
            spread_type=row[1],
            expiration=row[2],
            entry_date=row[3],
            net_debit=features.get("net_debit", 1.0),
            max_profit=features.get("max_profit", 1.0),
            max_loss=features.get("max_loss", 1.0),
            ml_score=features.get("ml_score", 50.0),
            outcome_score=float(row[5]),
        )
        # Convert outcome_score (0-100) to PnL %
        # 100 → max profit, 50 → breakeven, 0 → max loss
        if trade.outcome_score >= 50:
            pnl_ratio = (trade.outcome_score - 50) / 50 * (trade.max_profit / max(trade.net_debit, 0.01))
        else:
            pnl_ratio = -((50 - trade.outcome_score) / 50)
        trade.pnl_pct = round(pnl_ratio * 100, 2)
        trades.append(trade)

    winners = [t for t in trades if (t.pnl_pct or 0) > 0]
    losers = [t for t in trades if (t.pnl_pct or 0) <= 0]

    win_rate = len(winners) / len(trades) if trades else 0
    avg_win = sum(t.pnl_pct or 0 for t in winners) / max(len(winners), 1)
    avg_loss = sum(t.pnl_pct or 0 for t in losers) / max(len(losers), 1)
    total_return = sum(t.pnl_pct or 0 for t in trades)

    # Max drawdown (running cumulative PnL)
    cumulative = []
    running = 0.0
    for t in trades:
        running += t.pnl_pct or 0
        cumulative.append(running)
    peak = cumulative[0] if cumulative else 0
    max_dd = 0.0
    for c in cumulative:
        peak = max(peak, c)
        dd = peak - c
        max_dd = max(max_dd, dd)

    # ML score vs PnL correlation
    ml_scores = [t.ml_score for t in trades]
    pnls = [t.pnl_pct or 0 for t in trades]
    correlation = 0.0
    if len(trades) > 2:
        import numpy as np
        correlation = float(np.corrcoef(ml_scores, pnls)[0, 1])

    return BacktestResult(
        start_date=start_date,
        end_date=end_date,
        total_trades=len(trades),
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate=round(win_rate, 4),
        avg_winner_pct=round(avg_win, 2),
        avg_loser_pct=round(avg_loss, 2),
        total_return_pct=round(total_return, 2),
        max_drawdown_pct=round(max_dd, 2),
        ml_score_correlation=round(correlation, 4),
        summary=(
            f"{len(trades)} trades, {win_rate:.1%} win rate, "
            f"avg win {avg_win:.1f}%, avg loss {avg_loss:.1f}%, "
            f"ML correlation {correlation:.3f}"
        ),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="backend/ml/data/spread_outcomes.db")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    result = run_backtest(args.db, args.start, args.end)
    print(result.summary)
