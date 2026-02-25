"""Sentiment analysis API routes."""

import re

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.dependencies import get_cache, get_sentiment_scorer
from backend.api.cache import RedisCache
from backend.api.limiter import limiter
from backend.config.settings import get_settings
from backend.data.news_aggregator import NewsAggregator
from backend.data.yfinance_client import YFinanceClient
from backend.models.sentiment import TickerSentiment
from backend.sentiment.aggregator import SentimentAggregator
from backend.sentiment.sentiment_scorer import SentimentScorer

router = APIRouter()

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


def _validate_symbol(symbol: str) -> str:
    sym = symbol.upper().strip()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(status_code=400, detail="Invalid symbol format")
    return sym


@router.get("/{symbol}", response_model=TickerSentiment)
@limiter.limit(get_settings().RATE_LIMIT_SENTIMENT)
async def get_ticker_sentiment(
    request: Request,
    symbol: str,
    scorer: SentimentScorer = Depends(get_sentiment_scorer),
    cache: RedisCache = Depends(get_cache),
) -> TickerSentiment:
    """Fetch and score news sentiment for a single ticker."""
    sym = _validate_symbol(symbol)
    cache_key = f"sentiment_v2:{sym}"
    cached = await cache.get(cache_key)
    if cached:
        return TickerSentiment(**cached)

    yf_client = YFinanceClient()
    news_agg = NewsAggregator(yf_client)
    articles = await news_agg.get_news(sym)

    texts = [
        (a.title + " " + (a.description or "")).strip()
        for a in articles
        if a.title
    ]

    aggregator = SentimentAggregator()
    if not texts:
        from backend.scanner.scanner import _neutral_sentiment
        result = _neutral_sentiment(sym)
    else:
        results = await scorer.score_texts_async(texts)
        scored_articles = [a for a in articles if a.title]
        result = aggregator.aggregate(
            symbol=sym,
            results=results,
            articles=scored_articles,
            headlines=[a.title for a in articles[:5]],
        )

    await cache.set(cache_key, result.model_dump(), ttl=get_settings().CACHE_TTL_SENTIMENT)
    return result


@router.post("/batch", response_model=dict[str, TickerSentiment])
@limiter.limit(get_settings().RATE_LIMIT_SENTIMENT)
async def get_batch_sentiment(
    request: Request,
    symbols: list[str],
    scorer: SentimentScorer = Depends(get_sentiment_scorer),
    cache: RedisCache = Depends(get_cache),
) -> dict[str, TickerSentiment]:
    """Batch sentiment scoring for multiple tickers. Maximum 20 symbols per request."""
    import asyncio

    if not symbols:
        raise HTTPException(status_code=400, detail="symbols list cannot be empty")
    if len(symbols) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 symbols per batch request")

    # Validate all symbols before processing
    validated = []
    for s in symbols:
        validated.append(_validate_symbol(s))

    yf_client = YFinanceClient()
    news_agg = NewsAggregator(yf_client)
    aggregator = SentimentAggregator()

    async def fetch_one(symbol: str) -> tuple[str, TickerSentiment]:
        sym = symbol
        cached = await cache.get(f"sentiment_v2:{sym}")
        if cached:
            return sym, TickerSentiment(**cached)
        articles = await news_agg.get_news(sym)
        texts = [(a.title + " " + (a.description or "")).strip() for a in articles if a.title]
        if not texts:
            from backend.scanner.scanner import _neutral_sentiment
            return sym, _neutral_sentiment(sym)
        results = await scorer.score_texts_async(texts)
        scored_articles = [a for a in articles if a.title]
        sentiment = aggregator.aggregate(sym, results, scored_articles, [a.title for a in articles[:5]])
        await cache.set(f"sentiment_v2:{sym}", sentiment.model_dump(), get_settings().CACHE_TTL_SENTIMENT)
        return sym, sentiment

    tasks = [fetch_one(s) for s in validated]
    pairs = await asyncio.gather(*tasks, return_exceptions=True)
    return {sym: sent for sym, sent in pairs if not isinstance(sent, Exception)}
