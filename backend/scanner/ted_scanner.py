""""The Ted" — automated candidate discovery + direction-independent pre-screen.

Turns the manual ticker-search flow into an automated universe sweep. The
candidate list was empty because FMP's earnings-calendar endpoint 402s on the
free tier (HANDOFF §5); this rebuilds it from yfinance instead, with no FMP
dependency:

  1. Find universe symbols whose NEXT earnings fall in the Ted entry window
     (7-14 days out) — Gate 1.
  2. For those, confirm a listed expiry exists 1-2 days past earnings — Gate 2,
     the "great filter" — and attach the direction-independent pre-screen
     signals (Gate 6 attention, Gate 7 historical big mover).
  3. Rank. The user picks a candidate; /ted/check/{symbol} then runs the full
     14-gate directional checklist.

Direction-dependent gates (4 direction, 5 contra, 9 analyst, 10 drift,
11 sector, 14 BMO/AMC) are a human thesis and are deliberately NOT guessed here.

Cost is bounded: the earnings-date sweep is the only call made for every
symbol (cached per symbol for 24h), and the expiry/chain/past-move enrichment
runs only on the handful that clear the entry window.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Optional

from backend.scanner.ted_checker import (
    ATTENTION_MIN_CHAIN_OI,
    ATTENTION_MIN_MCAP,
    BIG_MOVE_MIN_COUNT,
    BIG_MOVE_PCT,
    IDEAL_DAYS_HIGH,
    IDEAL_DAYS_LOW,
    IV_EXCESS_LIMIT,
    MAX_DAYS_OUT,
    MAX_EXPIRY_PAST,
    MIN_DAYS_OUT,
    MIN_EXPIRY_PAST,
    TedInputs,
    TedMarketData,
    evaluate_gates,
)

DRIFT_LOOKBACK_SESSIONS = 5   # Gate 10: last close vs N sessions ago

# GICS / yfinance sector names → sector ETF for the Gate 11 trend check.
SECTOR_ETF = {
    "technology": "XLK", "information technology": "XLK",
    "financial services": "XLF", "financials": "XLF",
    "energy": "XLE",
    "healthcare": "XLV", "health care": "XLV",
    "consumer cyclical": "XLY", "consumer discretionary": "XLY",
    "consumer defensive": "XLP", "consumer staples": "XLP",
    "industrials": "XLI",
    "basic materials": "XLB", "materials": "XLB",
    "utilities": "XLU",
    "real estate": "XLRE",
    "communication services": "XLC",
}

logger = logging.getLogger(__name__)

CANDIDATES_CACHE_KEY = "ted:candidates"
BUILDING_FLAG_KEY = "ted:candidates:building"
EARNINGS_DATE_TTL = 24 * 3600     # per-symbol earnings date (earnings dates are static)
CANDIDATES_TTL = 6 * 3600         # the assembled list the API serves
BUILDING_TTL = 20 * 60            # self-clearing guard against duplicate builds
DEFAULT_CONCURRENCY = 8
_NO_DATE = ""                     # cache sentinel: "looked up, no earnings date"


# ---------------------------------------------------------------------------
# Market-data helper (shared with the /ted/check route)
# ---------------------------------------------------------------------------

def past_earnings_moves(symbol: str) -> list[float]:
    """Signed % next-day moves for the last 8 completed earnings (Gate 7).

    Direction-independent: Gate 7 keys off the *magnitude* of past moves.
    """
    import pandas as pd
    import yfinance as yf

    try:
        tk = yf.Ticker(symbol)
        edates = tk.get_earnings_dates(limit=12)
        if edates is None or edates.empty:
            return []
        hist = tk.history(period="2y", interval="1d")
        if hist.empty:
            return []
        hist.index = hist.index.tz_localize(None).normalize()
        closes = hist["Close"]

        moves: list[float] = []
        today = pd.Timestamp(date.today())
        for ts in edates.index:
            d = pd.Timestamp(ts).tz_localize(None).normalize()
            if d >= today:
                continue  # future earnings row
            before = closes[closes.index < d]
            after = closes[closes.index >= d]
            if before.empty or after.empty:
                continue
            move = (after.iloc[0] / before.iloc[-1] - 1) * 100
            moves.append(round(float(move), 2))
            if len(moves) >= 8:
                break
        return moves
    except Exception as e:
        logger.debug("past earnings moves failed %s: %s", symbol, e)
        return []


def drift_sign(symbol: str) -> Optional[int]:
    """+1 if the last close is above N sessions ago, -1 if below, None if unknown.

    Used to INFER the directional thesis (Gate 4) for the auto-evaluation — the
    user still confirms/overrides it in the per-symbol check.
    """
    import yfinance as yf

    try:
        hist = yf.Ticker(symbol).history(period="1mo", interval="1d")
        closes = hist["Close"].dropna()
        if len(closes) < DRIFT_LOOKBACK_SESSIONS + 1:
            return None
        change = float(closes.iloc[-1] - closes.iloc[-(DRIFT_LOOKBACK_SESSIONS + 1)])
        if change == 0:
            return 0
        return 1 if change > 0 else -1
    except Exception as e:
        logger.debug("drift sign failed %s: %s", symbol, e)
        return None


def hv90_pct(symbol: str) -> Optional[float]:
    """90-day historical volatility in IV points (HV-proxy for the 90d IV avg, Gate 12)."""
    import math

    import numpy as np
    import yfinance as yf

    try:
        hist = yf.Ticker(symbol).history(period="6mo", interval="1d")
        closes = hist["Close"].dropna()
        if len(closes) < 60:
            return None
        rets = np.log(closes / closes.shift(1)).dropna().tail(90)
        return float(rets.std() * math.sqrt(252) * 100)
    except Exception as e:
        logger.debug("hv90 failed %s: %s", symbol, e)
        return None


def fetch_sector_etf(symbol: str) -> Optional[str]:
    """Best-effort sector→ETF lookup via yfinance info (Gate 11). None on failure."""
    import yfinance as yf

    try:
        sector = (yf.Ticker(symbol).info or {}).get("sector", "")
        return SECTOR_ETF.get(str(sector).lower())
    except Exception as e:
        logger.debug("sector lookup failed %s: %s", symbol, e)
        return None


def full_gate_eval(
    *,
    symbol: str,
    earnings_date: date,
    expiry: Optional[date],
    direction: str,
    atm: Optional[dict],
    hv90: Optional[float],
    past_moves: list[float],
    market_cap: Optional[float],
    sector_etf: Optional[str],
    sector_trend_ok: Optional[bool],
    analyst_aligned: Optional[bool] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Run the full 14-gate checklist for the auto-inferred thesis and bucket it.

    Two gates cannot be auto-decided, so for the structural read we ASSUME them
    and the caller labels both 'confirm': Gate 5 (contra-catalyst) → no_contra,
    Gate 3 (sizing) → account sized to 100% of the contract cost. Gate 10 (price
    drift) is aligned by construction because the direction was inferred FROM
    drift. Returns the verdict, IV/direction sub-scores, and a tier:
        pass_all  = TRADE   (all auto gates clear for this thesis)
        pass_most = CAUTION
        weak      = WEAK / NO_TRADE
    """
    price = atm.get("price") if atm else None
    md = TedMarketData(
        earnings_date=earnings_date,
        expiration=expiry,
        option_price=price,
        theta_per_day=atm.get("theta_per_day") if atm else None,
        vega=atm.get("vega") if atm else None,
        market_cap=market_cap,
        chain_total_oi=atm.get("chain_oi") if atm else None,
        strike_oi=atm.get("oi") if atm else None,
        strike_bid=atm.get("bid") if atm else None,
        strike_ask=atm.get("ask") if atm else None,
        current_iv=atm.get("iv") if atm else None,
        avg_iv_90=hv90,
        past_moves=past_moves or [],
        price_drift_ok=True,            # direction inferred FROM drift → aligned
        sector_trend_ok=sector_trend_ok,
        sector_etf=sector_etf,
        analyst_aligned=analyst_aligned,
    )
    # Size the account so Gate 3 passes; the caller flags sizing as "confirm".
    account = (price * 100) if price else 1.0
    inp = TedInputs(
        symbol=symbol, direction=direction, account_balance=account,
        contracts=1, no_contra=True, bmo_amc="amc",
    )
    report = evaluate_gates(inp, md, today=today)
    tier = {"TRADE": "pass_all", "CAUTION": "pass_most"}.get(report.verdict, "weak")
    return {
        "verdict": report.verdict,
        "tier": tier,
        "iv_score": report.iv_score,
        "dir_score": report.dir_score,
        "gates_passed": sum(1 for g in report.gates if g.status == "pass"),
        "gates_total": len(report.gates),
        "hard_fails": report.hard_fails,
    }


def _pick_atm(chain, option_side: str):
    """Nearest-to-spot option on the given side, or None."""
    options = chain.calls if option_side == "call" else chain.puts
    spot = getattr(chain, "spot_price", None)
    if not options or not spot:
        return None
    return min(options, key=lambda o: abs(o.strike - spot))


async def atm_quote(yf_client, symbol: str, expiry_iso: str, side: str, sem=None) -> Optional[dict]:
    """ATM option iv(%)/mid/strike + whole-chain OI for one expiry, or None.

    Shared by scan-time entry capture and exit-time outcome labeling so both
    read the IV the same way.
    """
    try:
        if sem is not None:
            async with sem:
                chain = await yf_client.get_full_chain(symbol, expiry_iso)
        else:
            chain = await yf_client.get_full_chain(symbol, expiry_iso)
    except Exception as e:
        logger.debug("atm_quote chain failed %s %s: %s", symbol, expiry_iso, e)
        return None
    atm = _pick_atm(chain, side)
    if atm is None:
        return None
    mid = (atm.bid + atm.ask) / 2 if (atm.bid > 0 or atm.ask > 0) else atm.last
    return {
        "strike": atm.strike,
        "iv": round(atm.implied_volatility * 100, 1),
        "price": round(float(mid), 2) if mid else None,
        "bid": atm.bid,
        "ask": atm.ask,
        "oi": atm.open_interest,
        # Gate 13 wants $/contract/day (positive) and per-share vega, matching the
        # /check route's convention.
        "theta_per_day": abs(atm.theta) * 100,
        "vega": atm.vega,
        "chain_oi": int(
            sum(o.open_interest for o in chain.calls)
            + sum(o.open_interest for o in chain.puts)
        ),
    }


# ---------------------------------------------------------------------------
# Pure pre-screen logic (no I/O — unit-tested)
# ---------------------------------------------------------------------------

def iv_room(current_iv: Optional[float], avg_iv_90: Optional[float]) -> Optional[bool]:
    """Gate 12: True if current IV has room to run (not already > 90d avg + 20pts)."""
    if current_iv is None or avg_iv_90 is None:
        return None
    return (current_iv - avg_iv_90) <= IV_EXCESS_LIMIT

def qualifying_expiry(earnings_date: date, expirations: list[date]) -> Optional[date]:
    """Earliest listed expiry 1-2 days past earnings (Gate 2), or None."""
    quals = [
        e for e in expirations
        if MIN_EXPIRY_PAST <= (e - earnings_date).days <= MAX_EXPIRY_PAST
    ]
    return min(quals) if quals else None


def prescreen(
    earnings_date: date,
    expirations: list[date],
    past_moves: list[float],
    market_cap: Optional[float],
    chain_total_oi: Optional[int],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Direction-independent pre-screen of the automatable Ted gates.

    `qualifies` means both HARD, direction-independent gates pass: Gate 1
    (earnings 7-14 days out) and Gate 2 (a listed expiry 1-2 days past). A
    candidate that fails either can never be a TRADE regardless of thesis, so
    these pre-filter the list. The other signals (ideal window, Gate 6
    attention, Gate 7 big-mover) only rank among qualifiers.
    """
    today = today or date.today()
    days_out = (earnings_date - today).days
    qexp = qualifying_expiry(earnings_date, expirations or [])
    big = [m for m in (past_moves or []) if abs(m) >= BIG_MOVE_PCT]
    big_mover = len(big) >= BIG_MOVE_MIN_COUNT
    attention = bool(
        (market_cap or 0) >= ATTENTION_MIN_MCAP
        or (chain_total_oi or 0) >= ATTENTION_MIN_CHAIN_OI
    )
    ideal = IDEAL_DAYS_LOW <= days_out <= IDEAL_DAYS_HIGH
    in_window = MIN_DAYS_OUT <= days_out <= MAX_DAYS_OUT
    qualifies = in_window and qexp is not None
    score = int(ideal) + int(qexp is not None) + int(big_mover) + int(attention)
    return {
        "days_out": days_out,
        "ideal": ideal,
        "in_window": in_window,
        "qualifies": qualifies,
        "qualifying_expiry": qexp.isoformat() if qexp else None,
        "big_mover": big_mover,
        "big_mover_count": len(big),
        "past_move_sample": [round(m, 1) for m in (past_moves or [])[:8]],
        "attention": attention,
        "chain_total_oi": chain_total_oi,
        "prescreen_score": score,
    }


_TIER_RANK = {"pass_all": 0, "pass_most": 1, "weak": 2}


def rank_key(c: dict[str, Any]) -> tuple:
    """Qualifiers first, then by tier (pass_all > pass_most > weak), then score."""
    return (
        not c["qualifies"],
        _TIER_RANK.get(c.get("tier"), 3),
        -(c.get("iv_score") or 0),
        -(c.get("dir_score") or 0),
        not c["ideal"],
        -c["prescreen_score"],
        c["days_out"],
        c["symbol"],
    )


# ---------------------------------------------------------------------------
# Async discovery engine
# ---------------------------------------------------------------------------

async def discover_candidates(
    symbols: list[str],
    yf_client,
    cache,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    today: Optional[date] = None,
    enrich: bool = True,
) -> list[dict[str, Any]]:
    """Sweep `symbols` for Ted candidates and return a ranked list of dicts.

    One earnings-date lookup per symbol (cached 24h); expiry + chain-OI +
    past-move enrichment only for symbols that clear the 7-14 day window.
    Per-symbol failures are swallowed so one bad ticker never sinks the sweep.
    """
    today = today or date.today()
    sem = asyncio.Semaphore(concurrency)

    async def earnings_for(sym: str) -> Optional[date]:
        key = f"ted:edate:{sym}"
        try:
            cached = await cache.get(key)
        except Exception:
            cached = None
        if cached is not None:
            return date.fromisoformat(cached) if cached else None
        async with sem:
            ed = await yf_client.get_next_earnings_date(sym)
        try:
            await cache.set(key, ed.isoformat() if ed else _NO_DATE, EARNINGS_DATE_TTL)
        except Exception:
            pass
        return ed

    edates = await asyncio.gather(
        *[earnings_for(s) for s in symbols], return_exceptions=True
    )

    window: list[tuple[str, date]] = []
    for sym, ed in zip(symbols, edates):
        if isinstance(ed, Exception) or ed is None:
            continue
        d = (ed - today).days
        if MIN_DAYS_OUT <= d <= MAX_DAYS_OUT:
            window.append((sym, ed))

    async def enrich_one(sym: str, ed: date) -> dict[str, Any]:
        expirations: list[date] = []
        try:
            async with sem:
                raw = await yf_client.get_expirations(sym)
            for e in raw:
                try:
                    expirations.append(date.fromisoformat(e))
                except ValueError:
                    continue
        except Exception as ex:
            logger.debug("ted expiries failed %s: %s", sym, ex)

        past_moves: list[float] = []
        chain_oi: Optional[int] = None
        # Auto-evaluation extras (qualifiers only, to bound cost)
        inferred_direction: Optional[str] = None
        option_side: Optional[str] = None
        entry_iv = entry_price = atm_strike = None
        ivroom: Optional[bool] = None
        # Full-gate verdict / tier (qualifiers only)
        verdict: Optional[str] = None
        tier = "weak"
        iv_score = dir_score = gates_passed = None
        gates_total = None

        if enrich:
            try:
                past_moves = await asyncio.to_thread(past_earnings_moves, sym)
            except Exception:
                past_moves = []

            qexp = qualifying_expiry(ed, expirations)
            if qexp is not None:
                # Infer the directional thesis from drift (Gate 4), the HV-proxy
                # IV baseline (Gate 12), and the sector ETF (Gate 11) — parallel.
                try:
                    sign, hv90, sector_etf = await asyncio.gather(
                        asyncio.to_thread(drift_sign, sym),
                        asyncio.to_thread(hv90_pct, sym),
                        asyncio.to_thread(fetch_sector_etf, sym),
                    )
                except Exception:
                    sign, hv90, sector_etf = None, None, None
                if sign is not None and sign != 0:
                    inferred_direction = "bull" if sign > 0 else "bear"
                option_side = "put" if inferred_direction == "bear" else "call"

                # Sector trend alignment (Gate 11) vs the inferred direction.
                sector_trend_ok: Optional[bool] = None
                if sector_etf and inferred_direction:
                    etf_sign = await asyncio.to_thread(drift_sign, sector_etf)
                    if etf_sign is not None and etf_sign != 0:
                        up = etf_sign > 0
                        sector_trend_ok = up if inferred_direction == "bull" else not up

                q = await atm_quote(yf_client, sym, qexp.isoformat(), option_side, sem)
                if q is not None:
                    chain_oi = q["chain_oi"]
                    atm_strike = q["strike"]
                    entry_iv = q["iv"]
                    entry_price = q["price"]
                    ivroom = iv_room(entry_iv, hv90)

                # Full 14-gate checklist for the inferred thesis → verdict + tier.
                ge = full_gate_eval(
                    symbol=sym, earnings_date=ed, expiry=qexp,
                    direction=inferred_direction or "bull", atm=q, hv90=hv90,
                    past_moves=past_moves, market_cap=None,
                    sector_etf=sector_etf, sector_trend_ok=sector_trend_ok,
                    today=today,
                )
                verdict, tier = ge["verdict"], ge["tier"]
                iv_score, dir_score = ge["iv_score"], ge["dir_score"]
                gates_passed, gates_total = ge["gates_passed"], ge["gates_total"]

        ps = prescreen(ed, expirations, past_moves, None, chain_oi, today=today)
        return {
            "symbol": sym,
            "earnings_date": ed.isoformat(),
            **ps,
            "inferred_direction": inferred_direction,
            "option_side": option_side,
            "atm_strike": atm_strike,
            "entry_iv": entry_iv,
            "entry_price": entry_price,
            "iv_room": ivroom,
            "verdict": verdict,
            "tier": tier,
            "iv_score": iv_score,
            "dir_score": dir_score,
            "gates_passed": gates_passed,
            "gates_total": gates_total,
            # AMC-default exit target: exit before the print (Gate-aligned).
            "exit_by": ed.isoformat(),
        }

    results = await asyncio.gather(*[enrich_one(s, e) for s, e in window])
    results.sort(key=rank_key)
    return results


async def build_candidate_payload(
    symbols: list[str],
    yf_client,
    cache,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Run discovery and wrap it in the API/cache payload shape."""
    from datetime import datetime, timedelta, timezone

    today = today or date.today()
    candidates = await discover_candidates(
        symbols, yf_client, cache, concurrency=concurrency, today=today
    )
    n_qual = sum(1 for c in candidates if c["qualifies"])
    n_pass_all = sum(1 for c in candidates if c.get("tier") == "pass_all")
    n_pass_most = sum(1 for c in candidates if c.get("tier") == "pass_most")
    return {
        "candidates": candidates,
        "window": {
            "from": (today + timedelta(days=MIN_DAYS_OUT)).isoformat(),
            "to": (today + timedelta(days=MAX_DAYS_OUT)).isoformat(),
        },
        "source": "yfinance",
        "tiers": {"pass_all": n_pass_all, "pass_most": n_pass_most},
        "message": (
            ""
            if candidates
            else "No universe tickers report earnings in the 7-14 day window."
        ),
        "qualifying": n_qual,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
