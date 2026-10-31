"""Automated track record for "The Ted" (HANDOFF §5 follow-on).

Logs each scan's qualifying candidates with their entry IV, then — once the
exit-by date passes — records the IV at exit so the IV *buildup* the strategy
trades on can be measured without look-ahead bias (project goal #3: an honest
track record). Separate SQLite file from the main outcomes DB to avoid the
labeling lock contention documented in HANDOFF §6.

This module is DB-only (no network). The exit-side IV fetch lives in
`backend/scripts/ted_scan.py --label`, which reuses `ted_scanner.atm_quote`.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_DB = _PROJECT_ROOT / "backend" / "ml" / "data" / "ted_outcomes.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ted_candidates (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol             TEXT NOT NULL,
    earnings_date      TEXT NOT NULL,
    exit_by            TEXT,
    expiry             TEXT,
    option_side        TEXT,
    inferred_direction TEXT,
    atm_strike         REAL,
    entry_date         TEXT NOT NULL,
    entry_iv           REAL,
    entry_price        REAL,
    iv_room            INTEGER,
    big_mover_count    INTEGER,
    attention          INTEGER,
    prescreen_score    INTEGER,
    status             TEXT NOT NULL DEFAULT 'open',
    exit_iv            REAL,
    iv_change          REAL,
    exit_price         REAL,
    labeled_at         TEXT,
    UNIQUE(symbol, earnings_date)
);
"""


def _connect(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def log_candidates(payload: dict[str, Any], db_path: Path | str = DEFAULT_DB) -> int:
    """Upsert the qualifying candidates from a scan payload. Returns rows written.

    Entry fields refresh on a re-scan while the row is still 'open'; a 'labeled'
    row is never overwritten (first-passage-style: the recorded entry stands).
    """
    quals = [c for c in payload.get("candidates", []) if c.get("qualifies")]
    if not quals:
        return 0
    entry_date = date.today().isoformat()
    conn = _connect(db_path)
    try:
        for c in quals:
            conn.execute(
                """
                INSERT INTO ted_candidates
                  (symbol, earnings_date, exit_by, expiry, option_side,
                   inferred_direction, atm_strike, entry_date, entry_iv,
                   entry_price, iv_room, big_mover_count, attention, prescreen_score)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol, earnings_date) DO UPDATE SET
                   exit_by=excluded.exit_by,
                   expiry=excluded.expiry,
                   option_side=excluded.option_side,
                   inferred_direction=excluded.inferred_direction,
                   atm_strike=excluded.atm_strike,
                   entry_date=excluded.entry_date,
                   entry_iv=excluded.entry_iv,
                   entry_price=excluded.entry_price,
                   iv_room=excluded.iv_room,
                   big_mover_count=excluded.big_mover_count,
                   attention=excluded.attention,
                   prescreen_score=excluded.prescreen_score
                WHERE ted_candidates.status='open'
                """,
                (
                    c["symbol"], c["earnings_date"], c.get("exit_by"),
                    c.get("qualifying_expiry"), c.get("option_side"),
                    c.get("inferred_direction"), c.get("atm_strike"), entry_date,
                    c.get("entry_iv"), c.get("entry_price"),
                    1 if c.get("iv_room") else (0 if c.get("iv_room") is not None else None),
                    c.get("big_mover_count"), 1 if c.get("attention") else 0,
                    c.get("prescreen_score"),
                ),
            )
        conn.commit()
        return len(quals)
    finally:
        conn.close()


def due_for_label(
    db_path: Path | str = DEFAULT_DB, today: Optional[date] = None
) -> list[dict[str, Any]]:
    """Open rows whose exit_by has passed — ready for an exit-IV reading."""
    today = today or date.today()
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ted_candidates WHERE status='open' AND exit_by IS NOT NULL "
            "AND exit_by <= ? ORDER BY exit_by",
            (today.isoformat(),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def record_outcome(
    row_id: int,
    exit_iv: Optional[float],
    exit_price: Optional[float],
    db_path: Path | str = DEFAULT_DB,
) -> None:
    """Mark a row labeled with its exit IV; iv_change = exit_iv - entry_iv (the buildup)."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT entry_iv FROM ted_candidates WHERE id=?", (row_id,)
        ).fetchone()
        entry_iv = row["entry_iv"] if row else None
        iv_change = (
            round(exit_iv - entry_iv, 2)
            if (exit_iv is not None and entry_iv is not None) else None
        )
        conn.execute(
            "UPDATE ted_candidates SET status='labeled', exit_iv=?, iv_change=?, "
            "exit_price=?, labeled_at=? WHERE id=?",
            (exit_iv, iv_change, exit_price, datetime.now(timezone.utc).isoformat(), row_id),
        )
        conn.commit()
    finally:
        conn.close()


def summary(db_path: Path | str = DEFAULT_DB) -> dict[str, Any]:
    """Counts + mean IV buildup on labeled rows, for the CLI / a future dashboard."""
    conn = _connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM ted_candidates").fetchone()[0]
        open_n = conn.execute(
            "SELECT COUNT(*) FROM ted_candidates WHERE status='open'"
        ).fetchone()[0]
        labeled = conn.execute(
            "SELECT COUNT(*) FROM ted_candidates WHERE status='labeled'"
        ).fetchone()[0]
        row = conn.execute(
            "SELECT AVG(iv_change), SUM(CASE WHEN iv_change > 0 THEN 1 ELSE 0 END) "
            "FROM ted_candidates WHERE status='labeled' AND iv_change IS NOT NULL"
        ).fetchone()
        avg_iv_change = round(row[0], 2) if row[0] is not None else None
        iv_up = row[1] or 0
        return {
            "total": total, "open": open_n, "labeled": labeled,
            "avg_iv_change": avg_iv_change, "iv_up": iv_up,
        }
    finally:
        conn.close()
