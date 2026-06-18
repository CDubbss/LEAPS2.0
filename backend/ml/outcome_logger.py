"""
Logs ranked spread candidates to SQLite after each scan.

One row per spread candidate written to spread_outcomes with:
  - Entry prices (net debit, per-leg mids)
  - Underlying spot price at scan time
  - Full 23-feature vector (JSON) for ML training
  - Contract identifiers needed to re-fetch prices later

Called at the end of OptionsScanner.scan(). Safe to fail silently —
a logging error must never break a scan.

DB: backend/ml/data/spread_outcomes.db
"""

import json
import logging
import os
import sqlite3
from datetime import date, datetime

from backend.ml.features import FeatureEngineer
from backend.models.options import SpreadType
from backend.models.scanner import RankedSpread

logger = logging.getLogger(__name__)

DB_PATH = "backend/ml/data/spread_outcomes.db"


class OutcomeLogger:
    """
    Persists ranked spread candidates for ML outcome labeling.
    Thread-safe for single-writer use (SQLite serialized writes).
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._engineer = FeatureEngineer()
        try:
            self._ensure_schema()
        except Exception as e:
            logger.error("OutcomeLogger: failed to initialize DB at %s: %s", db_path, e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_scan_results(
        self,
        scan_id: str,
        ranked: list[RankedSpread],
        horizon_days: int = 30,
    ) -> int:
        """
        Persist a mixed sample of ranked spreads from one scan.

        Logs TOP_N best-ranked spreads plus RANDOM_N drawn from the remainder.
        The random tail reduces selection bias: without it the model only ever
        trains on candidates it already ranked highly, so it can never learn to
        penalize spreads it currently scores well but that perform poorly.

        Args:
            scan_id:      UUID from ScannerResult.scan_id
            ranked:       Sorted RankedSpread list (index 0 = best)
            horizon_days: Default MTM horizon used by label_outcomes.py

        Returns:
            Number of rows written (0 on error).
        """
        if not ranked:
            return 0

        # Earnings plays have fundamentally different P&L mechanics (IV expansion
        # around a catalyst) compared to directional LEAPS/spread strategies.
        # Keep them out of spread_outcomes so they don't skew the ranker model.
        _EARNINGS_TYPES = {SpreadType.EARNINGS_CALL, SpreadType.EARNINGS_PUT}
        eligible = [r for r in ranked if r.spread.spread_type not in _EARNINGS_TYPES]
        n_skipped = len(ranked) - len(eligible)
        if n_skipped:
            logger.debug("OutcomeLogger: skipped %d earnings candidates (kept separate)", n_skipped)

        to_log = eligible

        today = date.today().isoformat()
        rows = []

        for item in to_log:
            spread = item.spread
            fund = item.fundamentals
            sent = item.sentiment
            spot = spread.spot_price

            # Build full 23-feature vector using all available data
            try:
                fv = self._engineer.build(
                    spread=spread,
                    fundamentals=fund,
                    sentiment=sent,
                    spot_price=spot,
                    hv_30d=spread.hv_30d or 0.30,
                    iv_52w_high=spread.iv_52w_high or 0.60,
                    iv_52w_low=spread.iv_52w_low or 0.15,
                )
                fv_dict = fv.model_dump()
                # Attach spread economics and ML score so backtest.py can use
                # real dollar values and validate ML ranking quality.
                fv_dict["ml_score"] = round(item.ml_prediction.spread_quality_score, 4)
                fv_dict["max_profit"] = round(spread.max_profit, 4)
                fv_dict["max_loss"] = round(spread.max_loss, 4)
                fv_dict["net_debit"] = round(spread.net_debit, 4)
                features_json = json.dumps(fv_dict)
            except Exception as e:
                logger.warning("Feature build failed for %s: %s", spread.underlying, e)
                features_json = "{}"

            long = spread.long_leg
            short = spread.short_leg

            # Contract identifiers — used by label_outcomes.py to re-fetch prices.
            # spread_width is stored so _compute_spread_value_mtm can clamp
            # current_value to [0, spread_width] without needing strike data inline.
            contract = {
                "underlying": spread.underlying,
                "long_strike": long.strike,
                "long_option_type": long.option_type.value,
                "short_strike": short.strike if short else None,
                "short_option_type": short.option_type.value if short else None,
                "expiration": spread.expiration.isoformat(),
                "spread_width": round(abs(long.strike - short.strike), 2) if short else None,
            }

            rows.append((
                scan_id,
                spread.underlying,
                spread.spread_type.value,
                spread.expiration.isoformat(),
                today,
                None,               # outcome_score — filled by label_outcomes.py
                features_json,
                json.dumps(contract),
                spread.net_debit,
                long.mid,
                short.mid if short else None,
                spot,
                horizon_days,
            ))

        # Write spread candidates first — this is the critical write.
        n = 0
        try:
            with sqlite3.connect(self.db_path, timeout=60) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                before = conn.execute("SELECT COUNT(*) FROM spread_outcomes").fetchone()[0]
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO spread_outcomes (
                        scan_id, symbol, spread_type, expiration, entry_date,
                        outcome_score, features_json, contract_json,
                        entry_net_debit, long_mid_at_entry, short_mid_at_entry,
                        spot_at_entry, horizon_days
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                after = conn.execute("SELECT COUNT(*) FROM spread_outcomes").fetchone()[0]
                n = after - before
            logger.info(
                "Logged %d new spread candidates for scan %s (%d duplicates skipped)",
                n, scan_id, len(rows) - n,
            )
        except Exception as e:
            logger.error("OutcomeLogger: DB write failed: %s", e)
            return 0

        # Write scan event in a separate transaction so a missing scan_events
        # table never rolls back the spread_outcomes write above.
        try:
            with sqlite3.connect(self.db_path, timeout=10) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    """
                    INSERT OR IGNORE INTO scan_events (scan_id, entry_date, candidates_attempted, candidates_written)
                    VALUES (?, ?, ?, ?)
                    """,
                    (scan_id, today, len(rows), n),
                )
        except Exception as e:
            logger.warning("OutcomeLogger: scan_events write failed (non-critical): %s", e)

        return n

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Create tables and migrate missing columns idempotently."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)

        # Main candidates table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS spread_outcomes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id             TEXT,
                symbol              TEXT,
                spread_type         TEXT,
                expiration          TEXT,
                entry_date          TEXT,
                outcome_score       REAL,           -- 0-100, set by label_outcomes.py
                features_json       TEXT,           -- JSON of FeatureVector (23 features)
                contract_json       TEXT,           -- identifiers for price re-fetching
                entry_net_debit     REAL,           -- cost to enter the spread
                long_mid_at_entry   REAL,           -- long leg mid price at entry
                short_mid_at_entry  REAL,           -- short leg mid price at entry (nullable)
                spot_at_entry       REAL,           -- underlying price at scan time
                horizon_days        INTEGER DEFAULT 30,
                best_sell_days      INTEGER,        -- days since entry when peak P&L occurred
                peak_pnl_pct        REAL,           -- best P&L % achieved across all snapshots
                logged_at           TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Per-interval price snapshot table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                outcome_id      INTEGER NOT NULL REFERENCES spread_outcomes(id),
                days_since_entry INTEGER NOT NULL,
                snapshot_date   TEXT NOT NULL,
                current_value   REAL,           -- spread mid at snapshot
                pnl_pct         REAL,           -- (current - entry) / entry * 100
                outcome_score   REAL,           -- normalized pnl 0-100
                data_quality    TEXT DEFAULT 'ok',  -- 'ok' | 'clamped' | 'illiquid'
                fetched_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (outcome_id, days_since_entry)
            )
        """)

        # Migrate: add any missing columns to spread_outcomes
        new_cols = [
            ("contract_json",       "TEXT"),
            ("entry_net_debit",     "REAL"),
            ("long_mid_at_entry",   "REAL"),
            ("short_mid_at_entry",  "REAL"),
            ("spot_at_entry",       "REAL"),
            ("horizon_days",        "INTEGER DEFAULT 30"),
            ("best_sell_days",      "INTEGER"),
            ("peak_pnl_pct",        "REAL"),
        ]
        for col, typedef in new_cols:
            try:
                conn.execute(f"ALTER TABLE spread_outcomes ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass  # already exists

        # Scan event log — one row per scan regardless of deduplication.
        # Lets the UI show all scans, not just ones that added new spread rows.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_events (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id               TEXT UNIQUE,
                entry_date            TEXT,
                candidates_attempted  INTEGER,
                candidates_written    INTEGER,
                logged_at             TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()
