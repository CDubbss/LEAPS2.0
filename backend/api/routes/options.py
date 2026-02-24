"""Options chain API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.dependencies import get_cache, get_yf_client
from backend.api.cache import RedisCache
from backend.config.settings import get_settings
from backend.data.yfinance_client import YFinanceClient
from backend.models.options import OptionsChain

router = APIRouter()


@router.get("/historical/{symbol}/ohlc")
async def get_historical_ohlc(
    symbol: str,
    period: str = "1y",
    yf: YFinanceClient = Depends(get_yf_client),
) -> list[dict]:
    """OHLCV bars for candlestick chart. period: 1mo, 3mo, 6mo, 1y, 2y"""
    return await yf.get_historical_ohlc(symbol.upper(), period)


@router.get("/expirations/{symbol}", response_model=list[str])
async def get_expirations(
    symbol: str,
    yf: YFinanceClient = Depends(get_yf_client),
    cache: RedisCache = Depends(get_cache),
) -> list[str]:
    """Get all available option expiration dates for a symbol."""
    cache_key = f"expirations:{symbol.upper()}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    expirations = await yf.get_expirations(symbol.upper())
    await cache.set(cache_key, expirations, ttl=300)  # 5 min TTL
    return expirations


@router.get("/chain/{symbol}", response_model=OptionsChain)
async def get_options_chain(
    symbol: str,
    expiration: Optional[str] = Query(None, description="Expiration date (YYYY-MM-DD)"),
    yf: YFinanceClient = Depends(get_yf_client),
    cache: RedisCache = Depends(get_cache),
) -> OptionsChain:
    """
    Fetch full options chain for a symbol.
    If expiration is not specified, returns the nearest available expiry.
    """
    sym = symbol.upper()

    # Get available expirations
    expirations = await yf.get_expirations(sym)
    if not expirations:
        raise HTTPException(status_code=404, detail=f"No options found for {sym}")

    exp = expiration or expirations[0]
    if exp not in expirations:
        raise HTTPException(
            status_code=400,
            detail=f"Expiration {exp} not available. Options: {expirations[:5]}",
        )

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
    sym = symbol.upper()
    cache_key = f"quote:{sym}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    quote = await yf.get_quote(sym)
    await cache.set(cache_key, quote, ttl=get_settings().CACHE_TTL_QUOTES)
    return quote
