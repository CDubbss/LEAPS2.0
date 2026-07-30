"""
Positions tracker API — CRUD for spreads the user has actually entered,
with live mark-to-market pricing against the +50% target / -25% stop rules.

Routes are synchronous `def` on purpose: FastAPI runs them in a threadpool,
which is required because the yfinance pricing calls block.
"""

import logging
import os
import sqlite3
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import backend.ml.label_outcomes as lo

logger = logging.getLogger(__name__)

router = APIRouter()

_DB_PATH = "backend/ml/data/spread_outcomes.db"

STOP_LOSS_PCT = -50.0  # typical exit when spread P&L dips to -50% of debit


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol           TEXT NOT NULL,
                spread_type      TEXT NOT NULL DEFAULT 'leaps_spread_call',
                long_strike      REAL NOT NULL,
                long_option_type TEXT NOT NULL DEFAULT 'call',
                short_strike     REAL,
                short_option_type TEXT,
                expiration       TEXT NOT NULL,
                entry_date       TEXT NOT NULL,
                entry_debit      REAL NOT NULL,      -- per share
                contracts        INTEGER NOT NULL DEFAULT 10,
                status           TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'closed'
                exit_date        TEXT,
                exit_value       REAL,               -- per share, at close
                notes            TEXT,
                created_at       TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Ted (earnings IV-buildup) integration — exit-before-print tracking
        for col in ("earnings_date TEXT", "exit_by TEXT"):
            try:
                conn.execute(f"ALTER TABLE positions ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass  # already exists


_ensure_schema()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PositionCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    spread_type: str = "leaps_spread_call"
    long_strike: float = Field(gt=0)
    long_option_type: str = "call"
    short_strike: Optional[float] = Field(default=None, gt=0)
    short_option_type: Optional[str] = None
    expiration: str  # YYYY-MM-DD
    entry_date: str  # YYYY-MM-DD
    entry_debit: float = Field(gt=0, description="Net debit per share")
    contracts: int = Field(default=10, ge=1, le=100_000)
    notes: Optional[str] = Field(default=None, max_length=2000)
    # Ted positions: earnings date + hard exit-before-print deadline
    earnings_date: Optional[str] = None
    exit_by: Optional[str] = None


class PositionUpdate(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(open|closed)$")
    exit_date: Optional[str] = None
    exit_value: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=2000)
    contracts: Optional[int] = Field(default=None, ge=1, le=100_000)
    # Correction fields — fix data-entry mistakes without delete/re-add
    expiration: Optional[str] = None
    entry_date: Optional[str] = None
    entry_debit: Optional[float] = Field(default=None, gt=0)
    long_strike: Optional[float] = Field(default=None, gt=0)
    short_strike: Optional[float] = Field(default=None, gt=0)


class PositionOut(BaseModel):
    id: int
    symbol: str
    spread_type: str
    long_strike: float
    long_option_type: str
    short_strike: Optional[float]
    short_option_type: Optional[str]
    expiration: str
    entry_date: str
    entry_debit: float
    contracts: int
    status: str
    exit_date: Optional[str]
    exit_value: Optional[float]
    notes: Optional[str]
    earnings_date: Optional[str]
    exit_by: Optional[str]
    # Computed
    current_value: Optional[float]   # per share; None when pricing unavailable
    pnl_pct: Optional[float]
    pnl_dollars: Optional[float]
    target_pct: float                # commission-adjusted +50% threshold
    target_hit: bool
    stop_hit: bool
    days_held: int
    dte: int


# ---------------------------------------------------------------------------
# Pricing / enrichment
# ---------------------------------------------------------------------------

def _lenient_option_mid(
    provider: "lo._YFinanceProvider",
    underlying: str,
    expiry: str,
    strike: float,
    option_type: str,
) -> Optional[float]:
    """
    Option mid for position valuation. Unlike the labeler's fetcher, this does
    NOT reject wide markets — the user owns the position and a rough mark beats
    a blank. Clean quote → mid; wide quote (>50% of ask) → last trade if
    available; no bid/ask at all → last trade.
    """
    try:
        chain = provider._get_chain(underlying, expiry)
        df = chain.calls if option_type == "call" else chain.puts
        match = df[abs(df["strike"] - strike) < 0.01]
        if match.empty:
            return None
        bid = float(match["bid"].iloc[0])
        ask = float(match["ask"].iloc[0])
        last = 0.0
        for col in ("lastPrice", "last"):
            if col in match.columns:
                last = float(match[col].iloc[0]) or 0.0
                break
        if bid > 0 and ask >= bid:
            wide = (ask - bid) / ask > 0.50
            if wide and last > 0:
                return last
            return (bid + ask) / 2.0
        return last if last > 0 else None
    except Exception as e:
        logger.debug("Option fetch failed %s %s %.1f %s: %s",
                     underlying, expiry, strike, option_type, e)
        return None


def _price_open_position(row: sqlite3.Row, provider: "lo._YFinanceProvider") -> Optional[float]:
    """Return current per-share spread value, or None if quotes unavailable."""
    long_mid = _lenient_option_mid(
        provider, row["symbol"], row["expiration"],
        row["long_strike"], row["long_option_type"],
    )
    if long_mid is None:
        return None

    short_mid = 0.0
    if row["short_strike"] is not None:
        fetched = _lenient_option_mid(
            provider, row["symbol"], row["expiration"],
            row["short_strike"], row["short_option_type"] or row["long_option_type"],
        )
        if fetched is None:
            return None
        short_mid = fetched

    raw_value = long_mid - short_mid
    if row["short_strike"] is not None:
        width = abs(row["long_strike"] - row["short_strike"])
        return max(0.0, min(raw_value, width))
    return max(0.0, raw_value)


def _to_out(row: sqlite3.Row, current_value: Optional[float]) -> PositionOut:
    entry_debit = row["entry_debit"]
    today = date.today()

    # Closed positions are valued at their recorded exit
    if row["status"] == "closed" and row["exit_value"] is not None:
        current_value = row["exit_value"]

    pnl_pct = pnl_dollars = None
    if current_value is not None and entry_debit > 0:
        pnl_pct = round((current_value - entry_debit) / entry_debit * 100, 2)
        pnl_dollars = round((current_value - entry_debit) * 100 * row["contracts"], 2)

    target_pct = round(lo._commission_adjusted_target(entry_debit), 2)
    end = date.fromisoformat(row["exit_date"]) if row["exit_date"] else today
    days_held = max(0, (end - date.fromisoformat(row["entry_date"])).days)
    dte = (date.fromisoformat(row["expiration"]) - today).days

    return PositionOut(
        **{k: row[k] for k in (
            "id", "symbol", "spread_type", "long_strike", "long_option_type",
            "short_strike", "short_option_type", "expiration", "entry_date",
            "entry_debit", "contracts", "status", "exit_date", "exit_value", "notes",
            "earnings_date", "exit_by",
        )},
        current_value=round(current_value, 4) if current_value is not None else None,
        pnl_pct=pnl_pct,
        pnl_dollars=pnl_dollars,
        target_pct=target_pct,
        target_hit=pnl_pct is not None and pnl_pct >= target_pct,
        stop_hit=pnl_pct is not None and pnl_pct <= STOP_LOSS_PCT,
        days_held=days_held,
        dte=dte,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PositionOut])
def list_positions(refresh: bool = True) -> list[PositionOut]:
    """
    List all positions. Open positions are priced live via yfinance when
    refresh=true (default); pass refresh=false for a fast, price-free list.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM positions ORDER BY status ASC, entry_date DESC"
        ).fetchall()

    provider = lo._YFinanceProvider()  # fresh chain cache per request
    out = []
    for row in rows:
        current_value = None
        if row["status"] == "open" and refresh:
            try:
                current_value = _price_open_position(row, provider)
            except Exception as e:
                logger.warning("Pricing failed for position %d (%s): %s",
                               row["id"], row["symbol"], e)
        out.append(_to_out(row, current_value))
    return out


@router.post("", response_model=PositionOut, status_code=201)
def create_position(body: PositionCreate) -> PositionOut:
    try:
        exp = date.fromisoformat(body.expiration)
        date.fromisoformat(body.entry_date)
    except ValueError:
        raise HTTPException(422, "expiration and entry_date must be YYYY-MM-DD")
    if exp < date.today():
        raise HTTPException(
            422,
            f"expiration {body.expiration} is in the past — options expire on "
            "Fridays; double-check the year and day",
        )

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO positions (
                symbol, spread_type, long_strike, long_option_type,
                short_strike, short_option_type, expiration, entry_date,
                entry_debit, contracts, notes, earnings_date, exit_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                body.symbol.upper(), body.spread_type, body.long_strike,
                body.long_option_type, body.short_strike, body.short_option_type,
                body.expiration, body.entry_date, body.entry_debit,
                body.contracts, body.notes, body.earnings_date, body.exit_by,
            ),
        )
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _to_out(row, None)


@router.patch("/{position_id}", response_model=PositionOut)
def update_position(position_id: int, body: PositionUpdate) -> PositionOut:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(422, "No fields to update")
    for date_field in ("expiration", "entry_date", "exit_date"):
        if date_field in fields:
            try:
                date.fromisoformat(fields[date_field])
            except ValueError:
                raise HTTPException(422, f"{date_field} must be YYYY-MM-DD")
    if fields.get("status") == "closed" and "exit_date" not in fields:
        fields["exit_date"] = date.today().isoformat()

    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE positions SET {sets} WHERE id = ?",
            (*fields.values(), position_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, f"Position {position_id} not found")
        row = conn.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
    return _to_out(row, None)


@router.delete("/{position_id}", status_code=204)
def delete_position(position_id: int) -> None:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, f"Position {position_id} not found")
