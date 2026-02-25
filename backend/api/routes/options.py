"""Options chain API routes."""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.dependencies import get_cache, get_yf_client
from backend.api.cache import RedisCache
from backend.config.settings import get_settings
from backend.data.yfinance_client import YFinanceClient
from backend.models.options import OptionsChain

router = APIRouter()

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VALID_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y"}


def _validate_symbol(symbol: str) -> str:
    """Uppercase and validate a ticker symbol. Raises 400 on invalid input."""
    sym = symbol.upper().strip()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(status_code=400, detail="Invalid symbol format")
    return sym


@router.get("/historical/{symbol}/ohlc")
async def get_historical_ohlc(
    symbol: str,
    period: str = Query(default="1y", description="One of: 1mo, 3mo, 6mo, 1y, 2y, 5y"),
    yf: YFinanceClient = Depends(get_yf_client),
) -> list[dict]:
    """OHLCV bars for candlestick chart."""
    sym = _validate_symbol(symbol)
    if period not in _VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"period must be one of {sorted(_VALID_PERIODS)}")
    return await yf.get_historical_ohlc(sym, period)


@router.get("/expirations/{symbol}", response_model=list[str])
async def get_expirations(
    symbol: str,
    yf: YFinanceClient = Depends(get_yf_client),
    cache: RedisCache = Depends(get_cache),
) -> list[str]:
    """Get all available option expiration dates for a symbol."""
    sym = _validate_symbol(symbol)
    cache_key = f"expirations:{sym}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    expirations = await yf.get_expirations(sym)
    await cache.set(cache_key, expirations, ttl=300)
    return expirations


@router.get("/chain/{symbol}", response_model=OptionsChain)
async def get_options_chain(
    symbol: str,
    expiration: Optional[str] = Query(
        None,
        description="Expiration date (YYYY-MM-DD)",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    yf: YFinanceClient = Depends(get_yf_client),
    cache: RedisCache = Depends(get_cache),
) -> OptionsChain:
    """
    Fetch full options chain for a symbol.
    If expiration is not specified, returns the nearest available expiry.
    """
    sym = _validate_symbol(symbol)

    expirations = await yf.get_expirations(sym)
    if not expirations:
        raise HTTPException(status_code=404, detail="No options data found for the requested symbol")

    exp = expiration or expirations[0]
    if exp not in expirations:
        raise HTTPException(status_code=400, detail="Requested expiration date is not available")

    cache_key = f"chain:{sym}:{exp}"
    cached = await cache.get(cache_key)
    if cached:
        return OptionsChain(**cached)

    chain = await yf.get_full_chain(sym, exp)
    await cache.set(cache_key, chain.model_dump(), ttl=get_settings().CACHE_TTL_CHAINS)
    return chain


@router.get("/quote/{symbol}")
async def get_quote(
    symbol: str,
    yf: YFinanceClient = Depends(get_yf_client),
    cache: RedisCache = Depends(get_cache),
) -> dict:
    """Fetch real-time quote for a symbol."""
    sym = _validate_symbol(symbol)
    cache_key = f"quote:{sym}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    quote = await yf.get_quote(sym)
    await cache.set(cache_key, quote, ttl=get_settings().CACHE_TTL_QUOTES)
    return quote
