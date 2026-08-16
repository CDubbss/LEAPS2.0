"""
Automated outcome labeler for ML training data.

Two labeling modes
------------------
MTM (mark-to-market):
    For spreads where (today - entry_date) >= interval and expiration > today.
    Fetches current option mid prices — Schwab preferred, yfinance fallback.

Expiry:
    For spreads where expiration <= today.
    Uses historical stock close price to compute intrinsic spread value.

Price provider hierarchy
------------------------
At startup, _build_price_provider() tries to instantiate a SchwabPriceProvider
using the project's existing SchwabClient.  If Schwab credentials are absent or
the token is expired, it silently falls back to YFinancePriceProvider.

Schwab advantages over yfinance:
  - Real-time NBBO (not delayed / scraped)
  - Broker-calculated greeks
  - Reliable bid/ask; crossed markets do not occur

Snapshot collection
-------------------
Prices are recorded at SNAPSHOT_INTERVALS business days after entry.
Each snapshot row lands in the price_snapshots table.

Once all reachable intervals are snapped (or the option expires), the labeler:
  - Finds the day with the highest P&L (best_sell_days)
  - Sets outcome_score = score at that peak (0-100)
  - Sets peak_pnl_pct for inspection

Outcome score formula
---------------------
    pnl_pct       = (current_value - entry_net_debit) / entry_net_debit * 100
    outcome_score = clamp((pnl_pct + 100) / 2, 0, 100)

Mapping:
  -100% (total loss)  →   0
     0% (break-even)  →  50
   +100% (doubled)    → 100

Usage
-----
    # Collect due snapshots and label complete spreads
    python -m backend.ml.label_outcomes

    # Null bad historical data, reset labels, re-label from clean snapshots
    python -m backend.ml.label_outcomes --repair

    # Print data quality audit (recent bad-rate, distribution, rejections)
    python -m backend.ml.label_outcomes --audit

    # Null LEGACY boundary-pinned snapshots, then re-label (destructive)
    python -m backend.ml.label_outcomes --repair-clamped
    python -m backend.ml.label_outcomes

    # Preview without writing to DB
    python -m backend.ml.label_outcomes --dry-run

    # Use a non-default DB path
    python -m backend.ml.label_outcomes --db-path path/to/db
"""

import argparse
import json
import logging
import math
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import NamedTuple, Optional

import numpy as np
import pandas as pd
import yfinance as yf

DB_PATH = "backend/ml/data/spread_outcomes.db"

# Business days after entry when we collect price snapshots.
#
# Dense early coverage (days 3-60) catches short-term moves and momentum signals.
# Mid-range coverage (days 70-180) tracks trend development.
# Long LEAPS coverage (days 200-700) covers the full LEAPS hold period up to the
# maximum observed DTE (~720 business days / ~1009 calendar days).
SNAPSHOT_INTERVALS = [
    # Dense early — catch quick moves (3 bdays ≈ 1 week, 60 bdays ≈ 3 months)
    3, 5, 7, 10, 14, 21, 25, 28, 32, 35, 40, 45, 50, 55, 60,
    # Mid-range — trend development (70-180 bdays ≈ 3.5-9 months)
    70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180,
    # Long LEAPS — full hold period (200-700 bdays ≈ 10 months to ~3 years)
    200, 220, 240, 260, 280, 300, 330, 360, 390, 420, 450,
    480, 510, 540, 570, 600, 630, 660, 700,
]

# Tiered label thresholds (ascending tier rank).
# Each entry: (label_source, min_bdays_elapsed, max_snapshot_day_included)
#   min_bdays_elapsed         — bdays since entry required before this tier qualifies
#   max_snapshot_day_included — snapshots up to this day feed the best-P&L search
LABEL_TIERS = [
    ("interim_5d",    3,    5),   # best of days  3-5   (~1 calendar week)
    ("interim_10d",   7,   10),   # best of days  3-10  (~2 calendar weeks)
    ("interim_21d",  21,   21),   # best of days  3-21  (~1 month)
    ("interim_30d",  28,   35),   # best of days  3-35  (~7 weeks)
    ("interim_45d",  40,   45),   # best of days  3-45  (~2 months)
    ("interim_60d",  55,   60),   # best of days  3-60  (~3 months)
    ("interim_90d",  80,   90),   # best of days  3-90  (~4.5 months)
    ("interim_180d", 180,  180),  # best of days  3-180 (~9 months)
    ("interim_360d", 360,  360),  # best of days  3-360 (~18 months)
    ("interim_540d", 540,  540),  # best of days  3-540 (~27 months)
    ("interim_720d", 700,  700),  # best of days  3-700 (~36 months / max LEAPS DTE)
]

# Higher rank = more trustworthy label. expiry is the ceiling.
TIER_RANK: dict[str, int] = {
    "interim_5d":   1,
    "interim_10d":  2,
    "interim_21d":  3,
    "interim_30d":  4,
    "interim_45d":  5,
    "interim_60d":  6,
    "interim_90d":  7,
    "interim_180d": 8,
    "interim_360d": 9,
    "interim_540d": 10,
    "interim_720d": 11,
    "expiry":       12,
}


def _bdays_elapsed(entry: date, today: date) -> int:
    """Count business days between entry and today (exclusive of today)."""
    return int(np.busday_count(entry.isoformat(), today.isoformat()))


def _add_bdays(d: date, n: int) -> date:
    """Return the date that is n business days after d."""
    return date.fromisoformat(str(np.busday_offset(d.isoformat(), n, roll="forward")))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Outcome score helpers
# ---------------------------------------------------------------------------

def _score_from_pnl(pnl_pct: float) -> float:
    """Normalize P&L% to 0-100. Break-even = 50, +100% gain = 100."""
    return max(0.0, min(100.0, (pnl_pct + 100.0) / 2.0))


# ---------------------------------------------------------------------------
# yfinance price fetching
# ---------------------------------------------------------------------------

MAX_BID_ASK_SPREAD_PCT = 0.50  # reject mids where (ask-bid)/ask > 50% (illiquid)

# A vertical spread is ONE instrument and must be priced as one.  Requiring a
# live two-sided quote on every leg is what prevents the dominant historical
# failure mode: differencing a stale `lastPrice` print on one leg against a live
# mid on the other, which manufactures arbitrage-impossible spread values that
# were then clamped to a boundary and stored as if real.
#
# Set to False only to deliberately trade data quality for snapshot volume.
REQUIRE_TWO_SIDED_QUOTES = True

# A raw spread value slightly outside [0, width] is quote-tick noise and is
# snapped to the boundary.  Anything beyond this is a broken quote and is
# REJECTED rather than clamped -- clamping a broken quote yields exactly
# -100% or max-profit P&L, which permanently decides first-passage outcomes.
#
# Deliberately ABSOLUTE, not a fraction of width.  A bounds violation is a
# quote-mechanics artifact (options tick in $0.01-$0.05, a mid is a half-tick,
# and differencing two legs compounds that), so its plausible size does not
# scale with the spread.  A proportional tolerance would admit a $0.20
# violation on a $10 spread -- a real arbitrage breach, not rounding -- and
# clamping that to the floor stores a -100% P&L that trips the stop forever.
CLAMP_TOLERANCE = 0.05  # one full tick on nickel-quoted options

# data_quality values that represent a usable mark.  Anything else is recorded
# in snapshot_rejections and never written to price_snapshots.
USABLE_QUALITIES = frozenset({"ok", "clamped"})


# ---------------------------------------------------------------------------
# Price provider abstraction
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Quote:
    """
    A single option leg's price plus the provenance needed to judge it later.

    source:
        'quote' — live two-sided market (both bid and ask present)
        'last'  — fell back to a trade print of unknown age; unusable for
                  spread pricing under REQUIRE_TWO_SIDED_QUOTES
    last_trade: provider-supplied timestamp of the last trade, when available.
        Recorded but NOT yet gated on -- staleness rejection is a separate step.
    """
    mid: float
    bid: Optional[float]
    ask: Optional[float]
    source: str
    last_trade: Optional[str] = None


class SpreadMark(NamedTuple):
    """
    The result of pricing a spread, carrying the raw inputs alongside the
    corrected value so no future question about a row needs archaeology.

    current_value is NaN when data_quality is not usable, so existing callers
    that index result[0] and test `>= 0` correctly treat it as no-data.
    """
    current_value: float
    pnl_pct: float
    data_quality: str
    raw_value: Optional[float] = None
    spread_width: Optional[float] = None
    long_quote: Optional[_Quote] = None
    short_quote: Optional[_Quote] = None
    provider: Optional[str] = None

    @property
    def usable(self) -> bool:
        return self.data_quality in USABLE_QUALITIES


class _PriceProvider(ABC):
    """Minimal interface for fetching a live option quote."""

    @abstractmethod
    def fetch_option_quote(
        self,
        underlying: str,
        expiry_str: str,
        strike: float,
        option_type: str,
    ) -> Optional[_Quote]:
        """Return a _Quote or None if the contract is unavailable / illiquid."""

    def fetch_option_mid(
        self,
        underlying: str,
        expiry_str: str,
        strike: float,
        option_type: str,
    ) -> Optional[float]:
        """Backwards-compatible mid accessor."""
        q = self.fetch_option_quote(underlying, expiry_str, strike, option_type)
        return q.mid if q else None

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name for logging."""


class _YFinanceProvider(_PriceProvider):
    """
    yfinance-based option mid fetcher.

    Used as the fallback when Schwab credentials are absent or expired.
    Applies the 50% bid/ask quality gate to reject illiquid quotes.

    Chain cache
    -----------
    A single label_outcomes run may need the same symbol+expiry chain hundreds
    of times — once per snapshot interval per spread logged on that contract.
    The cache stores the raw OptionChain object keyed by (underlying, expiry_str)
    so each unique chain is downloaded exactly once per run.  The cache is
    cleared between runs by _build_price_provider() creating a fresh instance.
    """

    def __init__(self) -> None:
        # (underlying, expiry_str) -> yfinance OptionChain (has .calls / .puts DataFrames)
        self._chain_cache: dict[tuple[str, str], object] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def name(self) -> str:
        return "yfinance"

    def _get_chain(self, underlying: str, expiry_str: str):
        """Return cached OptionChain or download and cache it."""
        key = (underlying, expiry_str)
        if key not in self._chain_cache:
            self._chain_cache[key] = yf.Ticker(underlying).option_chain(expiry_str)
            self._cache_misses += 1
            if self._cache_misses % 50 == 0:
                logger.info(
                    "Chain cache: %d unique downloads, %d hits so far",
                    self._cache_misses, self._cache_hits,
                )
        else:
            self._cache_hits += 1
        return self._chain_cache[key]

    def log_cache_stats(self) -> None:
        total = self._cache_hits + self._cache_misses
        if total:
            logger.info(
                "Chain cache final: %d unique chains downloaded, "
                "%d cache hits (%.0f%% saved)",
                self._cache_misses, self._cache_hits,
                100 * self._cache_hits / total,
            )

    def fetch_option_quote(
        self,
        underlying: str,
        expiry_str: str,
        strike: float,
        option_type: str,
    ) -> Optional[_Quote]:
        try:
            chain = self._get_chain(underlying, expiry_str)
            df = chain.calls if option_type == "call" else chain.puts
            match = df[abs(df["strike"] - strike) < 0.01]
            if match.empty:
                return None

            last_trade = None
            if "lastTradeDate" in match.columns:
                raw_ts = match["lastTradeDate"].iloc[0]
                if raw_ts is not None and not pd.isna(raw_ts):
                    last_trade = str(raw_ts)

            bid = float(match["bid"].iloc[0])
            ask = float(match["ask"].iloc[0])

            # No live market on this leg.  Return the trade print tagged as
            # 'last' rather than swallowing it: the pair-pricing layer decides
            # whether it is acceptable, and the provenance is recorded either way.
            if bid <= 0 and ask <= 0:
                for col in ("lastPrice", "last"):
                    if col in match.columns:
                        last = float(match[col].iloc[0])
                        if last > 0:
                            return _Quote(
                                mid=last, bid=None, ask=None,
                                source="last", last_trade=last_trade,
                            )
                return None

            mid = (bid + ask) / 2.0
            if ask > 0 and (ask - bid) / ask > MAX_BID_ASK_SPREAD_PCT:
                logger.debug(
                    "Illiquid yfinance quote rejected %s %s %.1f %s: "
                    "bid=%.2f ask=%.2f (spread=%.0f%%)",
                    underlying, expiry_str, strike, option_type,
                    bid, ask, 100 * (ask - bid) / ask,
                )
                return None
            return _Quote(
                mid=mid, bid=bid, ask=ask,
                source="quote", last_trade=last_trade,
            )
        except Exception as e:
            logger.debug(
                "yfinance option fetch failed %s %s %.1f %s: %s",
                underlying, expiry_str, strike, option_type, e,
            )
            # Evict bad cache entry so a retry on the next interval doesn't
            # re-use a chain that failed to download
            self._chain_cache.pop((underlying, expiry_str), None)
            return None


class _SchwabProvider(_PriceProvider):
    """
    Schwab-based option mid fetcher using the project's existing SchwabClient.

    Calls the synchronous schwab-py client directly (no asyncio) since the
    labeler always runs outside an active event loop.  Applies the same 50%
    bid/ask quality gate as the yfinance provider.

    Preferred over yfinance because Schwab returns real-time NBBO with
    broker-calculated greeks; crossed or stale markets do not occur.
    """

    def __init__(self, schwab_client) -> None:
        self._client = schwab_client._client  # underlying sync schwab-py client

    @property
    def name(self) -> str:
        return "schwab"

    def fetch_option_quote(
        self,
        underlying: str,
        expiry_str: str,
        strike: float,
        option_type: str,
    ) -> Optional[_Quote]:
        try:
            from schwab.client import Client as SchwabClient
            exp = date.fromisoformat(expiry_str)
            contract_type = (
                SchwabClient.Options.ContractType.CALL
                if option_type == "call"
                else SchwabClient.Options.ContractType.PUT
            )
            resp = self._client.get_option_chain(
                underlying,
                contract_type=contract_type,
                from_date=exp,
                to_date=exp,
                strike_count=40,  # enough to find any reasonable strike
            )
            resp.raise_for_status()
            data = resp.json()

            exp_map_key = "callExpDateMap" if option_type == "call" else "putExpDateMap"
            exp_map = data.get(exp_map_key, {})

            for key, strikes_data in exp_map.items():
                if not key.startswith(expiry_str):
                    continue
                for strike_str, options in strikes_data.items():
                    if abs(float(strike_str) - strike) > 0.01:
                        continue
                    for opt in options:
                        bid = float(opt.get("bid") or 0)
                        ask = float(opt.get("ask") or 0)
                        if bid <= 0 and ask <= 0:
                            return None
                        if ask > 0 and (ask - bid) / ask > MAX_BID_ASK_SPREAD_PCT:
                            logger.debug(
                                "Illiquid Schwab quote rejected %s %s %.1f %s: "
                                "bid=%.2f ask=%.2f (spread=%.0f%%)",
                                underlying, expiry_str, strike, option_type,
                                bid, ask, 100 * (ask - bid) / ask,
                            )
                            return None
                        return _Quote(
                            mid=round((bid + ask) / 2.0, 4),
                            bid=bid, ask=ask, source="quote",
                            last_trade=opt.get("tradeTimeInLong") and str(
                                opt.get("tradeTimeInLong")
                            ),
                        )
            return None  # strike not found in chain
        except Exception as e:
            logger.debug(
                "Schwab option fetch failed %s %s %.1f %s: %s",
                underlying, expiry_str, strike, option_type, e,
            )
            return None


def _build_price_provider() -> _PriceProvider:
    """
    Return the price provider for snapshot collection.

    Uses yfinance only. Schwab was removed from label_outcomes because:
    - Access tokens expire in 30 min; repair runs take longer → mid-run refresh
    - schwab-py retries token refresh indefinitely on 400 (no timeout)
    - Failed refresh storms can trigger Schwab token revocation
    - yfinance is adequate for historical labeling purposes
    """
    logger.info("Price provider: yfinance")
    return _YFinanceProvider()


# Module-level singleton — built once per process, reused across calls.
# Replaced with a fresh instance at the start of each label_outcomes() run
# so token expiry within a long-running process is caught on next invocation.
_price_provider: Optional[_PriceProvider] = None


def _active_provider() -> _PriceProvider:
    """
    Return the active price provider, building one on first use.

    Callers outside label_outcomes() (e.g. the /api/v1/ml spread-detail route)
    reach the pricing helpers without going through the run entrypoint; without
    this the module-level singleton is still None and every such call raises.
    """
    global _price_provider
    if _price_provider is None:
        _price_provider = _build_price_provider()
    return _price_provider


def _fetch_option_quote(
    underlying: str,
    expiry_str: str,
    strike: float,
    option_type: str,
) -> Optional[_Quote]:
    """Delegate to the active price provider."""
    return _active_provider().fetch_option_quote(
        underlying, expiry_str, strike, option_type
    )


def _fetch_option_mid(
    underlying: str,
    expiry_str: str,
    strike: float,
    option_type: str,
) -> Optional[float]:
    """Backwards-compatible mid accessor."""
    q = _fetch_option_quote(underlying, expiry_str, strike, option_type)
    return q.mid if q else None


def _fetch_spot_at_date(underlying: str, target_date: date) -> Optional[float]:
    """
    Fetch the closing stock price on or after target_date.
    Used for intrinsic value computation at expiry.
    """
    try:
        end = target_date + timedelta(days=5)  # buffer for weekends/holidays
        hist = yf.Ticker(underlying).history(
            start=target_date.isoformat(),
            end=end.isoformat(),
        )
        if hist.empty:
            return None
        return float(hist["Close"].iloc[0])
    except Exception as e:
        logger.debug("History fetch failed %s %s: %s", underlying, target_date, e)
        return None


def _rejected(reason: str, **kw) -> SpreadMark:
    """Build an unusable SpreadMark carrying the evidence for the rejection."""
    return SpreadMark(
        current_value=math.nan, pnl_pct=math.nan, data_quality=reason, **kw
    )


def _compute_spread_value_mtm(contract: dict, entry_debit: float) -> Optional[SpreadMark]:
    """
    Price a spread ATOMICALLY -- both legs from the same chain snapshot, both
    with live two-sided quotes -- and return a SpreadMark.

    Returns None when a leg is simply absent from the chain (no data; the
    interval stays unrecorded and is retried on the next run).

    data_quality is one of:
        'ok'               — both legs live-quoted, raw value within bounds
        'clamped'          — raw value marginally outside bounds; snapped
        'rejected_stale'   — a leg had no live market (last-print fallback)
        'rejected_bounds'  — raw value materially outside [0, spread_width]

    Only 'ok' and 'clamped' are usable.  The two rejection states exist because
    a broken quote clamped to a boundary yields exactly -100% or max-profit
    P&L, which permanently and wrongly decides the ±50% first-passage outcome.
    Discarding the mark costs one row; keeping it corrupts a label forever.
    """
    provider_name = _active_provider().name

    long_q = _fetch_option_quote(
        contract["underlying"],
        contract["expiration"],
        contract["long_strike"],
        contract["long_option_type"],
    )
    if long_q is None:
        return None

    short_q = None
    short_mid = 0.0
    if contract.get("short_strike") is not None:
        short_q = _fetch_option_quote(
            contract["underlying"],
            contract["expiration"],
            contract["short_strike"],
            contract["short_option_type"],
        )
        if short_q is None:
            return None  # can't value a spread without both legs
        short_mid = short_q.mid

    spread_width = contract.get("spread_width") or abs(
        contract["long_strike"] - (contract.get("short_strike") or contract["long_strike"])
    )
    prov = {
        "spread_width": spread_width,
        "long_quote": long_q,
        "short_quote": short_q,
        "provider": provider_name,
    }

    # --- Gate 1: both legs must carry a live two-sided market -------------
    # Differencing a stale trade print against a live mid is what produced the
    # arbitrage-impossible spread values in the historical data.
    if REQUIRE_TWO_SIDED_QUOTES:
        stale = [
            side for side, q in (("long", long_q), ("short", short_q))
            if q is not None and q.source != "quote"
        ]
        if stale:
            logger.debug(
                "Rejected %s: no live market on %s leg(s)",
                contract.get("underlying"), "+".join(stale),
            )
            return _rejected("rejected_stale", raw_value=long_q.mid - short_mid, **prov)

    raw_value = long_q.mid - short_mid

    # --- Gate 2: theoretical bounds for a debit spread --------------------
    #   floor   = 0            (worthless at expiry)
    #   ceiling = spread_width (fully ITM at expiry)
    if spread_width > 0:
        lo, hi = 0.0, float(spread_width)
    else:
        lo, hi = 0.0, math.inf
    tolerance = CLAMP_TOLERANCE

    if raw_value < lo:
        violation = lo - raw_value
    elif raw_value > hi:
        violation = raw_value - hi
    else:
        violation = 0.0

    if violation > tolerance:
        logger.debug(
            "Rejected %s: raw=%.4f outside [0, %.2f] by %.4f (tolerance %.4f)",
            contract.get("underlying"), raw_value, spread_width, violation, tolerance,
        )
        return _rejected("rejected_bounds", raw_value=raw_value, **prov)

    current_value = max(lo, min(raw_value, hi))
    data_quality = "clamped" if violation > 0 else "ok"

    pnl_pct = (current_value - entry_debit) / entry_debit * 100.0
    return SpreadMark(
        current_value=current_value,
        pnl_pct=pnl_pct,
        data_quality=data_quality,
        raw_value=raw_value,
        **prov,
    )


def _compute_spread_value_at_expiry(
    contract: dict,
    entry_debit: float,
    expiry: date,
) -> Optional[SpreadMark]:
    """
    Compute spread intrinsic value at expiry using historical stock price.
    Returns a SpreadMark or None on failure.

    Intrinsic value is always deterministic from spot + strikes, so data_quality
    is always 'ok' here (no market bid/ask uncertainty).
    """
    spot = _fetch_spot_at_date(contract["underlying"], expiry)
    if spot is None:
        return None

    long_strike = contract["long_strike"]
    long_type = contract["long_option_type"]

    if long_type == "call":
        long_value = max(0.0, spot - long_strike)
    else:
        long_value = max(0.0, long_strike - spot)

    short_value = 0.0
    if contract.get("short_strike") is not None:
        short_strike = contract["short_strike"]
        short_type = contract.get("short_option_type", long_type)
        if short_type == "call":
            short_value = max(0.0, spot - short_strike)
        else:
            short_value = max(0.0, short_strike - spot)

    intrinsic = long_value - short_value
    pnl_pct = (intrinsic - entry_debit) / entry_debit * 100.0
    return SpreadMark(
        current_value=intrinsic,
        pnl_pct=pnl_pct,
        data_quality="ok",
        raw_value=intrinsic,
        provider="intrinsic",
    )


# ---------------------------------------------------------------------------
# Core labeling logic
# ---------------------------------------------------------------------------

def _record_rejection(
    conn: sqlite3.Connection,
    outcome_id: int,
    interval: int,
    snapshot_date: date,
    mark: SpreadMark,
) -> None:
    """
    Persist why a mark was discarded, keeping the raw leg quotes.

    Upserts on (outcome_id, days_since_entry) so a permanently unquotable
    contract holds one row carrying its latest reason and an attempt count,
    rather than appending a row on every daily run.
    """
    lq, sq = mark.long_quote, mark.short_quote
    conn.execute(
        """
        INSERT INTO snapshot_rejections
            (outcome_id, days_since_entry, snapshot_date, reason,
             raw_value, spread_width,
             long_bid, long_ask, long_source, long_last_trade,
             short_bid, short_ask, short_source, short_last_trade,
             price_provider, attempts, rejected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(outcome_id, days_since_entry) DO UPDATE SET
            reason          = excluded.reason,
            raw_value       = excluded.raw_value,
            long_bid        = excluded.long_bid,
            long_ask        = excluded.long_ask,
            long_source     = excluded.long_source,
            long_last_trade = excluded.long_last_trade,
            short_bid       = excluded.short_bid,
            short_ask       = excluded.short_ask,
            short_source    = excluded.short_source,
            short_last_trade= excluded.short_last_trade,
            price_provider  = excluded.price_provider,
            attempts        = snapshot_rejections.attempts + 1,
            rejected_at     = CURRENT_TIMESTAMP
        """,
        (
            outcome_id, interval, snapshot_date.isoformat(), mark.data_quality,
            None if mark.raw_value is None else round(mark.raw_value, 4),
            mark.spread_width,
            lq.bid if lq else None, lq.ask if lq else None,
            lq.source if lq else None, lq.last_trade if lq else None,
            sq.bid if sq else None, sq.ask if sq else None,
            sq.source if sq else None, sq.last_trade if sq else None,
            mark.provider,
        ),
    )


def collect_snapshots(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """
    For each unlabeled spread, collect any price snapshots that are due.
    A snapshot is due when days_since_entry >= interval and not yet recorded.

    Marks that fail the quality gates are recorded in snapshot_rejections and
    left out of price_snapshots, so the interval is retried on the next run.

    Returns total number of new snapshots written.
    """
    today = date.today()

    rows = conn.execute("""
        SELECT id, symbol, expiration, entry_date,
               entry_net_debit, contract_json
        FROM spread_outcomes
        WHERE COALESCE(label_source, '') != 'expiry'
          AND contract_json IS NOT NULL
          AND entry_net_debit IS NOT NULL
          AND entry_net_debit > 0
    """).fetchall()

    total_written = 0
    total_rejected = 0

    for row in rows:
        outcome_id = row[0]
        expiry = date.fromisoformat(row[2])
        entry = date.fromisoformat(row[3])
        entry_debit = row[4]
        contract = json.loads(row[5] or "{}")

        if not contract:
            continue

        bdays_elapsed = _bdays_elapsed(entry, today)

        # Which intervals are due and not yet recorded?
        existing = {
            r[0] for r in conn.execute(
                "SELECT days_since_entry FROM price_snapshots WHERE outcome_id = ?",
                (outcome_id,),
            )
        }

        for interval in SNAPSHOT_INTERVALS:
            if interval in existing:
                continue
            if bdays_elapsed < interval:
                break  # intervals are sorted; future ones aren't due yet

            snapshot_date = _add_bdays(entry, interval)

            # Choose valuation method based on whether option is expired
            if expiry <= snapshot_date:
                result = _compute_spread_value_at_expiry(contract, entry_debit, expiry)
                method = "expiry"
            else:
                result = _compute_spread_value_mtm(contract, entry_debit)
                method = "mtm"

            if result is None:
                logger.debug(
                    "Row %d interval %d: no price data (%s)", outcome_id, interval, method
                )
                continue

            # A rejected mark is NOT written to price_snapshots: the UNIQUE
            # (outcome_id, days_since_entry) constraint would permanently block
            # a good snapshot at that interval.  Leaving it unwritten preserves
            # the retry on the next run; the evidence goes to snapshot_rejections.
            if not result.usable:
                total_rejected += 1
                if not dry_run:
                    _record_rejection(conn, outcome_id, interval, snapshot_date, result)
                continue

            current_value, pnl_pct, data_quality = (
                result.current_value, result.pnl_pct, result.data_quality
            )
            score = _score_from_pnl(pnl_pct)

            logger.info(
                "%s [%s] day+%d: value=%.2f pnl=%.1f%% score=%.1f [%s]",
                contract.get("underlying", "?"), method, interval,
                current_value, pnl_pct, score, data_quality,
            )

            if not dry_run:
                lq, sq = result.long_quote, result.short_quote
                conn.execute(
                    """
                    INSERT OR IGNORE INTO price_snapshots
                        (outcome_id, days_since_entry, snapshot_date,
                         current_value, pnl_pct, outcome_score, data_quality,
                         raw_value, spread_width,
                         long_bid, long_ask, long_source, long_last_trade,
                         short_bid, short_ask, short_source, short_last_trade,
                         price_provider)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        outcome_id, interval, snapshot_date.isoformat(),
                        round(current_value, 4), round(pnl_pct, 2), round(score, 2),
                        data_quality,
                        None if result.raw_value is None else round(result.raw_value, 4),
                        result.spread_width,
                        lq.bid if lq else None, lq.ask if lq else None,
                        lq.source if lq else None, lq.last_trade if lq else None,
                        sq.bid if sq else None, sq.ask if sq else None,
                        sq.source if sq else None, sq.last_trade if sq else None,
                        result.provider,
                    ),
                )
                total_written += 1
                # Commit every 100 rows to release the write lock periodically,
                # allowing concurrent outcome_logger writes to proceed.
                if total_written % 100 == 0:
                    conn.commit()

    if not dry_run:
        conn.commit()

    if total_rejected:
        attempted = total_written + total_rejected
        logger.info(
            "Snapshots: %d written, %d rejected on quality gates (%.1f%% of %d attempted)",
            total_written, total_rejected,
            100.0 * total_rejected / attempted, attempted,
        )

    return total_written


PROFIT_TARGET_PCT = 50.0   # exit when spread P&L reaches +50%
STOP_LOSS_PCT = -50.0      # typical exit when P&L dips to -50% of debit

# Commission: $13 per 10-contract spread per side (open or close).
# Round trip = $26 for 10 contracts = $2.60/contract = $0.026/share.
COMMISSION_PER_CONTRACT = 2.60   # $13 / 10 contracts × 2 sides (open + close) ÷ 10
CONTRACTS_PER_TRADE     = 10


def _commission_adjusted_target(entry_debit: float) -> float:
    """
    Return the P&L % threshold that equals +50% profit AFTER commissions.

    Commission per share: $26 round trip / 10 contracts / 100 shares = $0.026
    The raw spread P&L must exceed 50% of debit PLUS commissions.
    """
    if not entry_debit or entry_debit <= 0:
        return PROFIT_TARGET_PCT
    commission_per_share = (COMMISSION_PER_CONTRACT * 2) / (CONTRACTS_PER_TRADE * 100)
    # Target P&L % = (target_dollar + commission) / entry_debit * 100
    target_dollar = entry_debit * (PROFIT_TARGET_PCT / 100) + commission_per_share
    return (target_dollar / entry_debit) * 100


def compute_strategy_outcomes(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """
    Walk each spread's snapshots CHRONOLOGICALLY and apply the exit rules —
    whichever threshold is touched first decides the outcome:

    Win  = P&L reached the commission-adjusted +50% target first
    Loss = P&L dipped to -50% first (typical stop — the trader exits there),
           OR the spread expired without ever reaching the target
    Open = neither threshold touched and not yet expired

    Recomputes ALL rows with snapshots on every run (not just unlabeled ones)
    so rule changes retroactively relabel history; writes only when the
    stored values actually change.

    Note: snapshots are interval-based — a dip below -50% between snapshot
    days is invisible, so stop-loss labels are snapshot-resolution.

    Sets on spread_outcomes:
      strategy_result  — 'win' | 'loss' | 'open'
      days_to_target   — days to first target touch (NULL if never)
      days_to_stop     — days to first -50% touch (NULL if never)
      strategy_pnl     — +50 if win, P&L at stop/expiry/last observation otherwise
    """
    rows = conn.execute("""
        SELECT so.id, so.entry_date, so.expiration, so.entry_net_debit,
               so.strategy_result, so.days_to_target, so.days_to_stop, so.strategy_pnl
        FROM spread_outcomes so
        WHERE EXISTS (
              SELECT 1 FROM price_snapshots ps
              WHERE ps.outcome_id = so.id AND ps.pnl_pct IS NOT NULL
          )
    """).fetchall()

    updated = 0
    counts = {"win": 0, "loss": 0, "open": 0}
    for (outcome_id, entry_str, expiry_str, entry_debit,
         old_result, old_dtt, old_dts, old_pnl) in rows:
        snaps = conn.execute(
            """
            SELECT days_since_entry, pnl_pct
            FROM price_snapshots
            WHERE outcome_id = ? AND pnl_pct IS NOT NULL
            ORDER BY days_since_entry
            """,
            (outcome_id,),
        ).fetchall()

        if not snaps:
            continue

        target_pct = _commission_adjusted_target(entry_debit)
        days_to_target = None
        days_to_stop = None
        result = None
        strategy_pnl = None

        # First-passage walk: whichever exit level is touched first wins
        for days, pnl in snaps:
            if pnl >= target_pct:
                result = "win"
                days_to_target = days
                strategy_pnl = PROFIT_TARGET_PCT
                break
            if pnl <= STOP_LOSS_PCT:
                result = "loss"
                days_to_stop = days
                strategy_pnl = pnl
                break

        if result is None:
            expiry = date.fromisoformat(expiry_str)
            if expiry <= date.today():
                result = "loss"          # expired without reaching the target
            else:
                result = "open"
            strategy_pnl = snaps[-1][1]

        counts[result] += 1

        strategy_pnl = round(strategy_pnl, 2)
        unchanged = (
            result == old_result
            and days_to_target == old_dtt
            and days_to_stop == old_dts
            and old_pnl is not None
            and abs(strategy_pnl - old_pnl) < 0.01
        )
        if unchanged or dry_run:
            continue

        conn.execute(
            """
            UPDATE spread_outcomes
            SET strategy_result = ?, days_to_target = ?,
                days_to_stop = ?, strategy_pnl = ?
            WHERE id = ?
            """,
            (result, days_to_target, days_to_stop, strategy_pnl, outcome_id),
        )
        updated += 1
        if updated % 500 == 0:
            conn.commit()

    if not dry_run:
        conn.commit()

    logger.info(
        "Strategy outcomes: %d win / %d loss / %d open (%d rows changed) "
        "[target=+%.0f%% after commissions, stop=%.0f%%]",
        counts["win"], counts["loss"], counts["open"], updated,
        PROFIT_TARGET_PCT, STOP_LOSS_PCT,
    )
    return updated


def finalize_outcomes(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """
    Assign or upgrade outcome labels using a tiered system.

    Tiers (ascending trustworthiness):
        interim_10d  → day-7 snapshot (~2 weeks signal)
        interim_21d  → best of days 7-21
        interim_30d  → best of days 7-35
        interim_90d  → best of days 7-90
        interim_180d → best of days 7-180
        interim_360d → best of days 7-360
        expiry       → actual intrinsic value at expiry (final)

    Each run upgrades rows to the highest tier they now qualify for.
    'expiry' is the ceiling — never overwritten.

    Returns number of rows updated.
    """
    today = date.today()

    # All rows not yet at the final expiry tier
    rows = conn.execute("""
        SELECT id, expiration, entry_date, label_source, entry_net_debit
        FROM spread_outcomes
        WHERE COALESCE(label_source, '') != 'expiry'
    """).fetchall()

    updated = 0

    for row in rows:
        outcome_id    = row[0]
        expiry        = date.fromisoformat(row[1])
        entry         = date.fromisoformat(row[2])
        current_src   = row[3] or ""
        current_rank  = TIER_RANK.get(current_src, 0)
        entry_debit   = row[4] or 0.0

        bdays_elapsed  = _bdays_elapsed(entry, today)
        option_expired = expiry <= today

        # Fetch all snapshots recorded so far, excluding rows nulled by repair_snapshots
        snaps = conn.execute(
            """
            SELECT days_since_entry, pnl_pct, outcome_score, current_value
            FROM price_snapshots
            WHERE outcome_id = ?
              AND pnl_pct IS NOT NULL
            ORDER BY days_since_entry
            """,
            (outcome_id,),
        ).fetchall()

        if not snaps:
            continue

        # Determine the best tier this spread qualifies for right now
        if option_expired:
            target_tier  = "expiry"
            target_snaps = snaps
        else:
            target_tier  = None
            target_snaps = None
            # Walk tiers highest → lowest; pick first one that qualifies
            for tier_name, min_bdays, max_snap_day in reversed(LABEL_TIERS):
                if bdays_elapsed < min_bdays:
                    continue
                window = [s for s in snaps if s[0] <= max_snap_day]
                if not window:
                    continue
                target_tier  = tier_name
                target_snaps = window
                break

        if target_tier is None:
            continue  # not enough time has passed for any tier

        new_rank = TIER_RANK[target_tier]
        if new_rank <= current_rank:
            continue  # already at this tier or higher — nothing to do

        # Best P&L within the qualifying snapshot window
        best                                   = max(target_snaps, key=lambda r: r[1])
        best_days, peak_pnl, peak_score, peak_value = best

        # Dollar P&L per contract: (current_value - entry_debit) * 100 shares/contract
        peak_pnl_dollars: Optional[float] = None
        if entry_debit and peak_value is not None:
            peak_pnl_dollars = round((peak_value - entry_debit) * 100, 2)

        logger.info(
            "outcome_id=%d  %s -> %s  best_sell_days=%d  pnl=%.1f%%  $%.2f  score=%.1f",
            outcome_id, current_src or "unlabeled", target_tier,
            best_days, peak_pnl, peak_pnl_dollars or 0.0, peak_score,
        )

        if not dry_run:
            conn.execute(
                """
                UPDATE spread_outcomes
                SET outcome_score    = ?,
                    label_source     = ?,
                    best_sell_days   = ?,
                    peak_pnl_pct     = ?,
                    peak_pnl_dollars = ?
                WHERE id = ?
                """,
                (
                    round(peak_score, 2), target_tier,
                    int(best_days), round(peak_pnl, 2),
                    peak_pnl_dollars,
                    outcome_id,
                ),
            )
            updated += 1

    if not dry_run:
        conn.commit()

    return updated


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Idempotent schema migration. Ensures all required columns and tables exist
    regardless of which version of the DB was originally created.
    Called at the top of label_outcomes() so the script is self-sufficient.
    """
    # New columns added after initial schema (train.py init_database)
    new_cols = [
        ("contract_json",       "TEXT"),
        ("entry_net_debit",     "REAL"),
        ("long_mid_at_entry",   "REAL"),
        ("short_mid_at_entry",  "REAL"),
        ("spot_at_entry",       "REAL"),
        ("horizon_days",        "INTEGER DEFAULT 30"),
        ("best_sell_days",      "INTEGER"),
        ("peak_pnl_pct",        "REAL"),
        ("peak_pnl_dollars",    "REAL"),   # dollar P&L per contract at peak (pnl_pct * entry_net_debit * 100)
        ("label_source",        "TEXT"),   # interim_10d … interim_360d | expiry
        ("strategy_result",     "TEXT"),   # win | loss | open
        ("days_to_target",      "INTEGER"),
        ("days_to_stop",        "INTEGER"),
        ("strategy_pnl",        "REAL"),
        # 1 = logged by a scan that ran while the NYSE was closed (weekend OR
        # holiday). yfinance still answers when the market is shut, serving the
        # previous session's closing chain: the quotes are real but the
        # entry_date is 1-3 days late and the row is usually a near-duplicate
        # of the prior trading day. Kept rather than deleted (the quotes are
        # genuine) but excluded from training, backtesting and validation.
        ("market_closed",       "INTEGER DEFAULT 0"),
    ]
    # weekend_scan was the earlier, narrower name for this flag; holidays have
    # the identical stale-quote problem, so it is one concept: market_closed.
    existing = {r[1] for r in conn.execute("PRAGMA table_info(spread_outcomes)")}
    if "weekend_scan" in existing and "market_closed" not in existing:
        conn.execute(
            "ALTER TABLE spread_outcomes RENAME COLUMN weekend_scan TO market_closed"
        )

    for col, typedef in new_cols:
        try:
            conn.execute(f"ALTER TABLE spread_outcomes ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # column already exists

    # Backfill market_closed. Weekends are computable in SQL (strftime('%w') is
    # 0=Sunday..6=Saturday); NYSE holidays are not (Good Friday needs Easter),
    # so they come from the Python calendar. Idempotent: only touches unmarked
    # rows, so it re-asserts cheaply on every run.
    conn.execute("""
        UPDATE spread_outcomes
        SET market_closed = 1
        WHERE COALESCE(market_closed, 0) = 0
          AND entry_date IS NOT NULL
          AND CAST(strftime('%w', entry_date) AS INTEGER) IN (0, 6)
    """)

    span = conn.execute(
        "SELECT MIN(entry_date), MAX(entry_date) FROM spread_outcomes "
        "WHERE entry_date IS NOT NULL"
    ).fetchone()
    if span and span[0]:
        from backend.data.market_calendar import NYSEHolidayCalendar

        import pandas as _pd
        idx = NYSEHolidayCalendar().holidays(start=span[0], end=span[1])
        hol = [d.date().isoformat() for d in _pd.DatetimeIndex(idx)]
        if hol:
            marks = ",".join("?" * len(hol))
            conn.execute(
                f"UPDATE spread_outcomes SET market_closed = 1 "
                f"WHERE COALESCE(market_closed, 0) = 0 AND entry_date IN ({marks})",
                hol,
            )

    # Price snapshots table (may not exist in older DBs)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            outcome_id       INTEGER NOT NULL REFERENCES spread_outcomes(id),
            days_since_entry INTEGER NOT NULL,
            snapshot_date    TEXT NOT NULL,
            current_value    REAL,
            pnl_pct          REAL,
            outcome_score    REAL,
            data_quality     TEXT DEFAULT 'ok',  -- 'ok' | 'clamped'
            fetched_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (outcome_id, days_since_entry)
        )
    """)
    # Migrate: add provenance columns to existing DBs.  The raw pre-clamp value
    # and per-leg quotes are kept so no future question about a stored row
    # requires re-deriving it from arbitrage reasoning.
    snapshot_cols = [
        ("data_quality",     "TEXT DEFAULT 'ok'"),
        ("raw_value",        "REAL"),   # pre-clamp long_mid - short_mid
        ("spread_width",     "REAL"),
        ("long_bid",         "REAL"),
        ("long_ask",         "REAL"),
        ("long_source",      "TEXT"),   # 'quote' | 'last'
        ("long_last_trade",  "TEXT"),
        ("short_bid",        "REAL"),
        ("short_ask",        "REAL"),
        ("short_source",     "TEXT"),
        ("short_last_trade", "TEXT"),
        ("price_provider",   "TEXT"),
    ]
    for col, typedef in snapshot_cols:
        try:
            conn.execute(f"ALTER TABLE price_snapshots ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # already exists

    # Marks discarded by the quality gates.  Kept out of price_snapshots so the
    # UNIQUE(outcome_id, days_since_entry) constraint there does not block a
    # later good snapshot at the same interval.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshot_rejections (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            outcome_id       INTEGER NOT NULL REFERENCES spread_outcomes(id),
            days_since_entry INTEGER NOT NULL,
            snapshot_date    TEXT NOT NULL,
            reason           TEXT NOT NULL,  -- 'rejected_stale' | 'rejected_bounds'
            raw_value        REAL,
            spread_width     REAL,
            long_bid         REAL,
            long_ask         REAL,
            long_source      TEXT,
            long_last_trade  TEXT,
            short_bid        REAL,
            short_ask        REAL,
            short_source     TEXT,
            short_last_trade TEXT,
            price_provider   TEXT,
            attempts         INTEGER DEFAULT 1,
            rejected_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (outcome_id, days_since_entry)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rejections_outcome "
        "ON snapshot_rejections (outcome_id)"
    )

    # Deduplicate spread_outcomes: for rows with a parseable contract_json,
    # keep only the highest-id row per (symbol, expiration, entry_date, strikes).
    # Highest id = most recent scan = most likely to have spread_width in contract_json.
    # Orphaned price_snapshots from deleted rows are removed afterwards.
    conn.execute("""
        DELETE FROM spread_outcomes
        WHERE contract_json IS NOT NULL
          AND id NOT IN (
            SELECT MAX(id)
            FROM spread_outcomes
            WHERE contract_json IS NOT NULL
            GROUP BY symbol, expiration, entry_date,
                     json_extract(contract_json, '$.long_strike'),
                     json_extract(contract_json, '$.short_strike')
          )
    """)
    conn.execute("""
        DELETE FROM price_snapshots
        WHERE outcome_id NOT IN (SELECT id FROM spread_outcomes)
    """)
    conn.execute("""
        DELETE FROM snapshot_rejections
        WHERE outcome_id NOT IN (SELECT id FROM spread_outcomes)
    """)

    # Create unique index to prevent future duplicates.
    # Rows with NULL contract_json are excluded (NULL != NULL in SQLite indexes).
    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_spread_fingerprint
            ON spread_outcomes (
                symbol, expiration, entry_date,
                json_extract(contract_json, '$.long_strike'),
                json_extract(contract_json, '$.short_strike')
            )
        """)
    except sqlite3.OperationalError as e:
        # Should not happen after the dedup above, but log if it does
        logger.warning("Could not create dedup index: %s", e)

    conn.commit()


def repair_snapshots(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """
    One-time (and safe-to-rerun) data repair pass.

    What it does
    ------------
    1. Marks bad snapshot rows (current_value < 0 or pnl_pct < -100) as
       data_quality='bad_data' and nulls their price/pnl/score columns.
       These values are impossible for a debit spread and indicate stale or
       crossed-market quotes from yfinance.

    2. Resets all non-expiry labels on spread_outcomes so that
       finalize_outcomes() re-derives them from the now-clean snapshots only.
       Expiry labels are ground truth (intrinsic value computation, not market
       quotes) and are left untouched.

    Returns a dict: {bad_snapshots_nulled, labels_reset}
    """
    # --- Step 1: Count and null bad snapshot rows ---
    bad_count = conn.execute("""
        SELECT COUNT(*) FROM price_snapshots
        WHERE current_value < 0 OR pnl_pct < -100
    """).fetchone()[0]

    if bad_count:
        logger.info("repair_snapshots: nulling %d bad snapshot rows", bad_count)
        if not dry_run:
            conn.execute("""
                UPDATE price_snapshots
                SET current_value = NULL,
                    pnl_pct       = NULL,
                    outcome_score = NULL,
                    data_quality  = 'bad_data'
                WHERE current_value < 0 OR pnl_pct < -100
            """)
    else:
        logger.info("repair_snapshots: no bad snapshots found")

    # --- Step 2: Reset all non-expiry labels so finalize re-derives cleanly ---
    # We reset all of them (not just the 196 driven by bad data) because any
    # label could be pointing at a snapshot that gets nulled in step 1, or
    # whose peer snapshots now look different. Finalize is fast and idempotent.
    reset_count = conn.execute("""
        SELECT COUNT(*) FROM spread_outcomes
        WHERE label_source IS NOT NULL AND label_source != 'expiry'
    """).fetchone()[0]

    if reset_count:
        logger.info("repair_snapshots: resetting %d non-expiry labels for re-labeling", reset_count)
        if not dry_run:
            conn.execute("""
                UPDATE spread_outcomes
                SET outcome_score    = NULL,
                    label_source     = NULL,
                    best_sell_days   = NULL,
                    peak_pnl_pct     = NULL,
                    peak_pnl_dollars = NULL
                WHERE label_source IS NOT NULL AND label_source != 'expiry'
            """)

    if not dry_run:
        conn.commit()

    return {"bad_snapshots_nulled": bad_count, "labels_reset": reset_count}


def repair_clamped_snapshots(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """
    Null legacy boundary-pinned snapshots written before bounds violations were
    rejected instead of clamped.

    Targets rows where data_quality='clamped' AND raw_value IS NULL -- the NULL
    raw_value is what identifies a pre-provenance row.  Rows written by the
    current collector keep their raw value and are only ever clamped within
    tolerance, so they are left alone.

    This is opt-in and separate from --repair because it discards a large block
    of history: a floor-pinned row stores exactly -100% P&L, which trips the
    -50% stop on first passage and marks the spread a loss forever, from a
    quote that was arbitrage-impossible.

    Callers must re-run labeling afterwards so outcomes are re-derived.

    Returns a dict: {clamped_nulled, labels_reset, strategy_reset}
    """
    n = conn.execute("""
        SELECT COUNT(*) FROM price_snapshots
        WHERE data_quality = 'clamped' AND raw_value IS NULL
    """).fetchone()[0]

    if not n:
        logger.info("repair_clamped: no legacy clamped rows found")
        return {"clamped_nulled": 0, "labels_reset": 0, "strategy_reset": 0}

    logger.info("repair_clamped: nulling %d legacy boundary-pinned rows", n)
    if not dry_run:
        conn.execute("""
            UPDATE price_snapshots
            SET current_value = NULL,
                pnl_pct       = NULL,
                outcome_score = NULL,
                data_quality  = 'bad_data'
            WHERE data_quality = 'clamped' AND raw_value IS NULL
        """)

    # Reset non-expiry labels AND strategy verdicts -- both are derived from the
    # snapshots being nulled, and compute_strategy_outcomes() only recomputes
    # rows that still have at least one non-null snapshot.
    labels = conn.execute("""
        SELECT COUNT(*) FROM spread_outcomes
        WHERE label_source IS NOT NULL AND label_source != 'expiry'
    """).fetchone()[0]
    strategy = conn.execute(
        "SELECT COUNT(*) FROM spread_outcomes WHERE strategy_result IS NOT NULL"
    ).fetchone()[0]

    if not dry_run:
        conn.execute("""
            UPDATE spread_outcomes
            SET outcome_score    = NULL,
                label_source     = NULL,
                best_sell_days   = NULL,
                peak_pnl_pct     = NULL,
                peak_pnl_dollars = NULL
            WHERE label_source IS NOT NULL AND label_source != 'expiry'
        """)
        conn.execute("""
            UPDATE spread_outcomes
            SET strategy_result = NULL,
                days_to_target  = NULL,
                days_to_stop    = NULL,
                strategy_pnl    = NULL
        """)
        conn.commit()

    logger.info(
        "repair_clamped: reset %d labels and %d strategy verdicts — re-run labeling",
        labels, strategy,
    )
    return {"clamped_nulled": n, "labels_reset": labels, "strategy_reset": strategy}


def quality_audit(db_path: str = DB_PATH, window_hours: int = 24) -> dict:
    """
    Report snapshot data quality metrics and warn if the recent bad rate is high.

    Checks all snapshots added in the last `window_hours` for data_quality != 'ok'.
    Logs a WARNING if the bad rate exceeds 5% on a meaningful sample (>10 rows).

    Returns a summary dict suitable for logging or display.
    """
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    total = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    total_bad = conn.execute(
        "SELECT COUNT(*) FROM price_snapshots WHERE data_quality != 'ok'"
    ).fetchone()[0]

    recent_total = conn.execute(f"""
        SELECT COUNT(*) FROM price_snapshots
        WHERE fetched_at > datetime('now', '-{window_hours} hours')
    """).fetchone()[0]
    recent_bad = conn.execute(f"""
        SELECT COUNT(*) FROM price_snapshots
        WHERE fetched_at > datetime('now', '-{window_hours} hours')
          AND data_quality != 'ok'
    """).fetchone()[0]

    dist = dict(conn.execute(
        "SELECT COALESCE(data_quality,'ok'), COUNT(*) FROM price_snapshots GROUP BY data_quality"
    ).fetchall())

    # Legacy boundary-pinned rows: written before bounds violations were
    # rejected rather than clamped.  A floor clamp stores exactly -100% P&L and
    # a ceiling clamp stores max profit, either of which permanently decides a
    # ±50% first-passage outcome from what was an impossible quote.
    legacy_floor = conn.execute(
        "SELECT COUNT(*) FROM price_snapshots "
        "WHERE data_quality = 'clamped' AND pnl_pct <= -99.9"
    ).fetchone()[0]
    legacy_ceiling = conn.execute(
        "SELECT COUNT(*) FROM price_snapshots "
        "WHERE data_quality = 'clamped' AND pnl_pct > 0 AND raw_value IS NULL"
    ).fetchone()[0]

    try:
        rejections = dict(conn.execute(
            "SELECT reason, COUNT(*) FROM snapshot_rejections GROUP BY reason"
        ).fetchall())
        recent_rejections = conn.execute(f"""
            SELECT COUNT(*) FROM snapshot_rejections
            WHERE rejected_at > datetime('now', '-{window_hours} hours')
        """).fetchone()[0]
    except sqlite3.OperationalError:
        rejections, recent_rejections = {}, 0  # table predates this schema

    conn.close()

    bad_rate = recent_bad / recent_total if recent_total else 0.0

    if recent_total > 10 and bad_rate > 0.05:
        logger.warning(
            "DATA QUALITY ALERT — clamped snapshot rate in last %dh: %.1f%% (%d/%d). "
            "Check yfinance option chain availability or consider Schwab fallback.",
            window_hours, bad_rate * 100, recent_bad, recent_total,
        )
    else:
        logger.info(
            "Snapshot quality — last %dh: %d written, %.1f%% clamped, %d rejected",
            window_hours, recent_total, bad_rate * 100, recent_rejections,
        )

    if legacy_floor or legacy_ceiling:
        logger.warning(
            "LEGACY CLAMPED DATA — %d floor-pinned (-100%%) and %d ceiling-pinned "
            "rows predate bounds rejection and still feed labels. "
            "Run --repair-clamped to null them, then re-label.",
            legacy_floor, legacy_ceiling,
        )

    return {
        "total_snapshots": total,
        "total_bad_all_time": total_bad,
        f"last_{window_hours}h_total": recent_total,
        f"last_{window_hours}h_bad": recent_bad,
        f"last_{window_hours}h_bad_rate_pct": round(bad_rate * 100, 1),
        "quality_distribution": dist,
        "legacy_floor_clamped": legacy_floor,
        "legacy_ceiling_clamped": legacy_ceiling,
        "rejections_all_time": rejections,
        f"rejections_last_{window_hours}h": recent_rejections,
    }


def label_outcomes(
    db_path: str = DB_PATH,
    dry_run: bool = False,
    repair: bool = False,
) -> dict:
    """
    Main entry point. Collect due snapshots then finalize complete spreads.

    Builds the best available price provider (Schwab → yfinance) at the start
    of each run so token expiry is caught on the next invocation.

    Args:
        repair: If True, run repair_snapshots() first to null bad historical
                data before collecting new snapshots and re-labeling.

    Returns summary dict: {snapshots_collected, outcomes_finalized,
                           bad_snapshots_nulled, labels_reset}
    """
    global _price_provider
    _price_provider = _build_price_provider()

    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    repair_result = {"bad_snapshots_nulled": 0, "labels_reset": 0}
    try:
        _migrate(conn)
        if repair:
            repair_result = repair_snapshots(conn, dry_run=dry_run)
        snapshots = collect_snapshots(conn, dry_run=dry_run)
        finalized = finalize_outcomes(conn, dry_run=dry_run)
        strategy  = compute_strategy_outcomes(conn, dry_run=dry_run)
    finally:
        conn.close()
        # Log chain cache efficiency if provider supports it
        if hasattr(_price_provider, "log_cache_stats"):
            _price_provider.log_cache_stats()

    audit = quality_audit(db_path)

    summary = {
        "snapshots_collected": snapshots,
        "outcomes_finalized": finalized,
        "strategy_outcomes": strategy,
        "price_provider": _price_provider.name,
        **repair_result,
    }
    logger.info("label_outcomes complete: %s", summary)
    return summary


def print_summary(db_path: str = DB_PATH) -> None:
    """Print a quick status table of the training DB including tier breakdown."""
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM spread_outcomes").fetchone()[0]
    labeled = conn.execute(
        "SELECT COUNT(*) FROM spread_outcomes WHERE outcome_score IS NOT NULL"
    ).fetchone()[0]
    snapshots = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    avg_best_sell = conn.execute(
        "SELECT AVG(best_sell_days) FROM spread_outcomes WHERE best_sell_days IS NOT NULL"
    ).fetchone()[0]
    avg_pnl_pct = conn.execute(
        "SELECT AVG(peak_pnl_pct) FROM spread_outcomes WHERE peak_pnl_pct IS NOT NULL"
    ).fetchone()[0]
    avg_pnl_dollars = conn.execute(
        "SELECT AVG(peak_pnl_dollars) FROM spread_outcomes WHERE peak_pnl_dollars IS NOT NULL"
    ).fetchone()[0]

    tier_counts = conn.execute(
        "SELECT COALESCE(label_source, 'unlabeled'), COUNT(*) "
        "FROM spread_outcomes GROUP BY label_source ORDER BY label_source"
    ).fetchall()
    conn.close()

    w = 48
    print(f"\n{'='*w}")
    print(f"  Spread outcomes DB: {db_path}")
    print(f"{'='*w}")
    print(f"  Total logged:       {total}")
    print(f"  Labeled:            {labeled}")
    print(f"  Unlabeled:          {total - labeled}")
    print(f"  Price snapshots:    {snapshots}")
    if avg_best_sell is not None:
        print(f"  Avg best sell day:  {avg_best_sell:.1f}")
    if avg_pnl_pct is not None:
        print(f"  Avg peak P&L %:     {avg_pnl_pct:+.1f}%")
    if avg_pnl_dollars is not None:
        print(f"  Avg peak P&L $:     ${avg_pnl_dollars:+.2f} per contract")
    print(f"  {'-'*44}")
    print(f"  {'Label source':<20} {'Count':>6}  {'Weight':>6}")
    print(f"  {'-'*44}")
    from backend.ml.train import LABEL_WEIGHTS
    for src, cnt in tier_counts:
        wt = LABEL_WEIGHTS.get(src, 1.0)
        print(f"  {src:<20} {cnt:>6}  {wt:>6.2f}")
    print(f"  {'-'*44}")

    # Strategy stats (50% target / 25% stop)
    conn2 = sqlite3.connect(db_path)
    strat = conn2.execute("""
        SELECT strategy_result, COUNT(*), ROUND(AVG(days_to_target), 1)
        FROM spread_outcomes
        WHERE strategy_result IS NOT NULL
        GROUP BY strategy_result
    """).fetchall()
    if strat:
        print(f"  {'Strategy (50/25)':<20} {'Count':>6}  {'Avg days':>6}")
        print(f"  {'-'*44}")
        total_strat = sum(r[1] for r in strat)
        wins = next((r for r in strat if r[0] == 'win'), None)
        losses = next((r for r in strat if r[0] == 'loss'), None)
        opens = next((r for r in strat if r[0] == 'open'), None)
        if wins:
            print(f"  {'win':<20} {wins[1]:>6}  {wins[2] or 0:>6}")
        if losses:
            print(f"  {'loss':<20} {losses[1]:>6}  {'':>6}")
        if opens:
            print(f"  {'open':<20} {opens[1]:>6}  {'':>6}")
        win_count = wins[1] if wins else 0
        decided = win_count + (losses[1] if losses else 0)
        if decided > 0:
            print(f"  {'Win rate':<20} {win_count/decided*100:>5.1f}%")
    conn2.close()
    print(f"{'='*w}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Collect price snapshots and label spread outcomes for ML training."
    )
    parser.add_argument("--db-path", default=DB_PATH, help="Path to spread_outcomes.db")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch prices and log what would happen, but don't write to DB.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print DB status and exit.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Null bad historical snapshots and reset affected labels before re-labeling.",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Print snapshot data quality audit and exit.",
    )
    parser.add_argument(
        "--repair-clamped",
        action="store_true",
        help=(
            "Null LEGACY boundary-pinned snapshots (pre-provenance 'clamped' rows) "
            "and reset all derived labels. Destructive and large — run --audit first, "
            "then re-run labeling afterwards."
        ),
    )
    args = parser.parse_args()

    if args.summary:
        print_summary(args.db_path)
    elif args.audit:
        result = quality_audit(args.db_path)
        print("\n=== Snapshot Quality Audit ===")
        print(f"  Total snapshots:       {result['total_snapshots']}")
        print(f"  Bad all-time:          {result['total_bad_all_time']}")
        print(f"  Last 24h total:        {result['last_24h_total']}")
        print(f"  Last 24h bad:          {result['last_24h_bad']}  ({result['last_24h_bad_rate_pct']}%)")
        print(f"  Quality distribution:  {result['quality_distribution']}")
        print(f"  Legacy floor-pinned:   {result['legacy_floor_clamped']}  (stored as -100% P&L)")
        print(f"  Legacy ceiling-pinned: {result['legacy_ceiling_clamped']}")
        print(f"  Rejections all-time:   {result['rejections_all_time'] or '{}'}")
        print(f"  Rejections last 24h:   {result['rejections_last_24h']}")
        print()
    elif args.repair_clamped:
        conn = sqlite3.connect(args.db_path, timeout=60)
        conn.execute("PRAGMA journal_mode=WAL")
        _migrate(conn)
        res = repair_clamped_snapshots(conn, dry_run=args.dry_run)
        conn.close()
        tag = " (DRY RUN)" if args.dry_run else ""
        print(
            f"\nrepair-clamped{tag}: {res['clamped_nulled']} snapshots nulled, "
            f"{res['labels_reset']} labels and {res['strategy_reset']} strategy "
            f"verdicts reset.\nRe-run labeling to re-derive them.\n"
        )
    else:
        result = label_outcomes(args.db_path, dry_run=args.dry_run, repair=args.repair)
        tag = " (DRY RUN)" if args.dry_run else ""
        print(
            f"\nDone{tag}: {result['snapshots_collected']} snapshots collected, "
            f"{result['outcomes_finalized']} outcomes finalized.\n"
        )
        print_summary(args.db_path)
