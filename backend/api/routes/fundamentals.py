"""Fundamentals API routes."""

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_cache, get_fmp_client
from backend.api.cache import RedisCache
from backend.config.settings import get_settings
from backend.data.fmp_client import FMPClient
from backend.models.fundamentals import FundamentalData
from backend.scanner.fundamentals_scorer import FundamentalsScorer

router = APIRouter()

_scorer = FundamentalsScorer()


@router.get("/{symbol}", response_model=FundamentalData)
async def get_fundamentals(
    symbol: str,
    fmp: FMPClient = Depends(get_fmp_client),
    cache: RedisCache = Depends(get_cache),
) -> FundamentalData:
    """Fetch and score company fundamentals for a symbol."""
    sym = symbol.upper()
    cache_key = f"fundamentals:{sym}"
    cached = await cache.get(cache_key)
    if cached:
        return FundamentalData(**cached)

    async with fmp:
        fund = await fmp.get_full_fundamentals(sym)

    fund = _scorer.score(fund)
    await cache.set(cache_key, fund, ttl=get_settings().CACHE_TTL_FUNDAMENTALS)
    return fund
