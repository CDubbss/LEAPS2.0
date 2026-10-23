"""
"The Ted" — Earnings IV-Buildup strategy API.

GET /candidates       — universe symbols with earnings 7-14 days out
GET /check/{symbol}   — run the 14-gate checklist with auto-gathered market data

Market-data gathering happens here; gate logic lives in
backend/scanner/ted_checker.py (pure, unit-testable).
"""

import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.cache import RedisCache
from backend.api.dependencies import get_cache, get_fmp_client, get_yf_client
from backend.data.fmp_client import FMPClient
from backend.data.yfinance_client import YFinanceClient
from backend.models.fundamentals import FundamentalData
from backend.scanner.ted_checker import (
    MAX_DAYS_OUT,
    MAX_EXPIRY_PAST,
    MIN_DAYS_OUT,
    MIN_EXPIRY_PAST,
    TedInputs,
    TedMarketData,
    TedReport,
    evaluate_gates,
)
from backend.scanner.universe import DEFAULT_UNIVERSE

logger = logging.getLogger(__name__)

router = APIRouter()

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

# GICS / FMP sector names → sector ETF used for the Gate 11 trend check
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

DRIFT_LOOKBACK_SESSIONS = 5   # Gates 10/11: compare last close vs N sessions ago
STRIKE_MENU_SPAN = 0.10       # strike menu: within ±10% of spot
STRIKE_MENU_MAX = 9


def _validate_symbol(symbol: str) -> str:
    sym = symbol.upper().strip()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(status_code=400, detail="Invalid symbol format")
    return sym


# ---------------------------------------------------------------------------
# Candidates — earnings 7-14 days out
# ---------------------------------------------------------------------------

@router.get("/candidates")
async def get_candidates(
    fmp: FMPClient = Depends(get_fmp_client),
    cache: RedisCache = Depends(get_cache),
) -> dict:
    """
    Universe symbols with earnings inside the valid Ted entry window (7-14 days).
    Primary source: FMP earnings-calendar (one call). Cached for 6 hours.
    """
    cache_key = "ted:candidates"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    today = date.today()
    lo = today + timedelta(days=MIN_DAYS_OUT)
    hi = today + timedelta(days=MAX_DAYS_OUT)

    async with fmp:
        rows = await fmp.get_earnings_calendar(lo, hi)

    universe = set(DEFAULT_UNIVERSE)
    seen: set[str] = set()
    candidates = []
    for row in rows:
        sym = str(row.get("symbol", "")).upper()
        date_str = str(row.get("date", ""))[:10]
        if sym not in universe or sym in seen or not date_str:
            continue
        try:
            edate = date.fromisoformat(date_str)
        except ValueError:
            continue
        days_out = (edate - today).days
        if days_out < MIN_DAYS_OUT or days_out > MAX_DAYS_OUT:
            continue
        seen.add(sym)
        candidates.append({
            "symbol": sym,
            "earnings_date": edate.isoformat(),
            "days_out": days_out,
            "ideal": 10 <= days_out <= 12,
        })

    candidates.sort(key=lambda c: (c["days_out"], c["symbol"]))
    result = {
        "candidates": candidates,
        "window": {"from": lo.isoformat(), "to": hi.isoformat()},
        "source": "fmp" if rows else "none",
        "message": (
            "" if rows else
            "FMP earnings calendar unavailable on this plan — "
            "search a ticker directly; its earnings date is fetched per symbol."
        ),
    }
    await cache.set(cache_key, result, ttl=6 * 3600)
    return result


# ---------------------------------------------------------------------------
# Market-data helpers (sync, run in threads)
# ---------------------------------------------------------------------------

def _past_earnings_moves(symbol: str) -> list[float]:
    """Absolute-signed % next-day moves for the last 8 completed earnings."""
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
            # close strictly before earnings vs first close on/after it
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


def _trend_ok(symbol: str, direction: str) -> Optional[bool]:
    """True when the last close moved in the thesis direction vs N sessions ago."""
    import yfinance as yf

    try:
        hist = yf.Ticker(symbol).history(period="1mo", interval="1d")
        closes = hist["Close"].dropna()
        if len(closes) < DRIFT_LOOKBACK_SESSIONS + 1:
            return None
        change = closes.iloc[-1] - closes.iloc[-(DRIFT_LOOKBACK_SESSIONS + 1)]
        return bool(change > 0) if direction == "bull" else bool(change < 0)
    except Exception as e:
        logger.debug("trend check failed %s: %s", symbol, e)
        return None


def _hv90_pct(symbol: str) -> Optional[float]:
    """90-day historical volatility in IV points (HV-proxy for the 90d IV avg)."""
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


async def _get_fundamentals(sym: str, fmp: FMPClient, cache: RedisCache) -> FundamentalData:
    cached = await cache.get(f"fundamentals:{sym}")
    if cached:
        return FundamentalData(**cached)
    async with fmp:
        return await fmp.get_full_fundamentals(sym)


# ---------------------------------------------------------------------------
# Gate check
# ---------------------------------------------------------------------------

@router.get("/check/{symbol}")
async def check_symbol(
    symbol: str,
    direction: Literal["bull", "bear"] = Query(...),
    account_balance: float = Query(..., gt=0),
    contracts: int = Query(default=1, ge=1),
    strike: Optional[float] = Query(default=None, gt=0),
    expiration: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    expected_iv_gain: float = Query(default=10.0, gt=0),
    bmo_amc: Literal["bmo", "amc"] = Query(default="amc"),
    no_contra: bool = Query(default=False),
    attention_override: Optional[bool] = Query(default=None),
    analyst_override: Optional[bool] = Query(default=None),
    yf_client: YFinanceClient = Depends(get_yf_client),
    fmp: FMPClient = Depends(get_fmp_client),
    cache: RedisCache = Depends(get_cache),
) -> dict:
    """Run the full 14-gate Ted checklist for one symbol."""
    sym = _validate_symbol(symbol)
    option_side = "call" if direction == "bull" else "put"

    # 1. Earnings date + sector + market cap (cached fundamentals)
    fund = await _get_fundamentals(sym, fmp, cache)
    earnings_date = fund.next_earnings_date
    if isinstance(earnings_date, str):  # defensive: cache may hold ISO strings
        earnings_date = date.fromisoformat(earnings_date[:10])

    # 2. Qualifying expiry: 1-2 days past earnings (Gate 2)
    expirations = await yf_client.get_expirations(sym)
    exp_dates = []
    for e in expirations:
        try:
            exp_dates.append(date.fromisoformat(e))
        except ValueError:
            continue

    chosen_expiry: Optional[date] = None
    if expiration:
        chosen_expiry = date.fromisoformat(expiration)
    elif earnings_date is not None:
        qualifying = [
            e for e in exp_dates
            if MIN_EXPIRY_PAST <= (e - earnings_date).days <= MAX_EXPIRY_PAST
        ]
        if qualifying:
            chosen_expiry = min(qualifying)
        else:
            # nearest expiry after earnings — Gate 2 will hard-fail, but the
            # UI can still show the chain and explain why
            after = [e for e in exp_dates if e > earnings_date]
            chosen_expiry = min(after) if after else None

    # 3. Chain at the chosen expiry → strike menu + chosen contract
    strike_menu: list[dict] = []
    chosen: Optional[dict] = None
    spot = None
    chain_total_oi = None
    if chosen_expiry is not None:
        try:
            chain = await yf_client.get_full_chain(sym, chosen_expiry.isoformat())
            spot = chain.spot_price
            options = chain.calls if option_side == "call" else chain.puts
            chain_total_oi = int(
                sum(o.open_interest for o in chain.calls)
                + sum(o.open_interest for o in chain.puts)
            )
            near = [
                o for o in options
                if spot and abs(o.strike - spot) / spot <= STRIKE_MENU_SPAN
            ]
            near.sort(key=lambda o: abs(o.strike - (spot or 0)))
            for o in near[:STRIKE_MENU_MAX]:
                mid = (o.bid + o.ask) / 2 if (o.bid > 0 or o.ask > 0) else o.last
                strike_menu.append({
                    "strike": o.strike,
                    "bid": o.bid, "ask": o.ask, "mid": round(mid, 2),
                    "open_interest": o.open_interest, "volume": o.volume,
                    "iv": round(o.implied_volatility * 100, 1),
                    "delta": round(o.delta, 3),
                    "theta": round(o.theta, 4),
                    "vega": round(o.vega, 4),
                })
            strike_menu.sort(key=lambda s: s["strike"])
            if strike is not None:
                chosen = next((s for s in strike_menu if abs(s["strike"] - strike) < 0.01), None)
            if chosen is None and strike_menu:
                chosen = min(strike_menu, key=lambda s: abs(s["strike"] - (spot or 0)))
        except Exception as e:
            logger.warning("Ted chain fetch failed %s %s: %s", sym, chosen_expiry, e)

    # 4. Slow lookups in parallel threads
    sector_etf = SECTOR_ETF.get((fund.sector or "").lower())
    moves_t = asyncio.to_thread(_past_earnings_moves, sym)
    drift_t = asyncio.to_thread(_trend_ok, sym, direction)
    hv90_t = asyncio.to_thread(_hv90_pct, sym)
    sector_t = (
        asyncio.to_thread(_trend_ok, sector_etf, direction)
        if sector_etf else asyncio.sleep(0, result=None)
    )
    consensus_t = fmp.get_price_target_consensus(sym)
    past_moves, drift_ok, hv90, sector_ok, consensus = await asyncio.gather(
        moves_t, drift_t, hv90_t, sector_t, consensus_t
    )

    # Gate 9: consensus target meaningfully beyond spot in the thesis direction
    analyst_aligned: Optional[bool] = None
    if consensus and spot:
        target = consensus.get("targetConsensus") or consensus.get("targetMedian")
        if target:
            analyst_aligned = (
                float(target) > spot * 1.05 if direction == "bull"
                else float(target) < spot * 0.95
            )

    md = TedMarketData(
        earnings_date=earnings_date,
        expiration=chosen_expiry,
        option_price=(chosen["mid"] if chosen and chosen["mid"] > 0 else
                      chosen["ask"] if chosen else None),
        theta_per_day=abs(chosen["theta"]) * 100 if chosen else None,
        vega=chosen["vega"] if chosen else None,
        market_cap=fund.market_cap,
        chain_total_oi=chain_total_oi,
        strike_oi=chosen["open_interest"] if chosen else None,
        strike_bid=chosen["bid"] if chosen else None,
        strike_ask=chosen["ask"] if chosen else None,
        current_iv=chosen["iv"] if chosen else None,
        avg_iv_90=hv90,
        past_moves=past_moves,
        price_drift_ok=drift_ok,
        sector_trend_ok=sector_ok,
        sector_etf=sector_etf,
        analyst_aligned=analyst_override if analyst_override is not None else analyst_aligned,
    )
    inputs = TedInputs(
        symbol=sym, direction=direction, account_balance=account_balance,
        contracts=contracts, expected_iv_gain=expected_iv_gain,
        bmo_amc=bmo_amc, no_contra=no_contra,
        attention_override=attention_override, analyst_override=analyst_override,
    )
    report: TedReport = evaluate_gates(inputs, md)

    return {
        "report": report.model_dump(mode="json"),
        "context": {
            "spot": spot,
            "earnings_date": earnings_date.isoformat() if earnings_date else None,
            "expiration": chosen_expiry.isoformat() if chosen_expiry else None,
            "expirations_near_earnings": [
                e.isoformat() for e in exp_dates
                if earnings_date and -3 <= (e - earnings_date).days <= 7
            ],
            "option_side": option_side,
            "chosen_strike": chosen["strike"] if chosen else None,
            "strike_menu": strike_menu,
            "sector": fund.sector,
            "sector_etf": sector_etf,
            "company_name": fund.company_name,
        },
    }
