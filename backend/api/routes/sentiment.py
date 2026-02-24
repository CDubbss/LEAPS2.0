"""Sentiment analysis API routes."""

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_cache, get_sentiment_scorer
from backend.api.cache import RedisCache
from backend.config.settings import get_settings
from backend.data.news_aggregator import NewsAggregator
from backend.data.yfinance_client import YFinanceClient
from backend.models.sentiment import TickerSentiment
from backend.sentiment.aggregator import SentimentAggregator
from backend.sentiment.sentiment_scorer import SentimentScorer

router = APIRouter()


@router.get("/{symbol}", response_model=TickerSentiment)
async def get_ticker_sentiment(
    symbol: str,
    scorer: SentimentScorer = Depends(get_sentiment_scorer),
    cache: RedisCache = Depends(get_cache),
) -> TickerSentiment:
    """Fetch and score news sentiment for a single ticker."""
    sym = symbol.upper()
    cache_key = f"sentiment:{sym}"
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
        result = aggregator.aggregate(
            symbol=sym,
            results=results,
            headlines=[a.title for a in articles[:5]],
        )

    await cache.set(cache_key, result.model_dump(), ttl=get_settings().CACHE_TTL_SENTIMENT)
    return result


@router.post("/batch", response_model=dict[str, TickerSentiment])
async def get_batch_sentiment(
    symbols: list[str],
    scorer: SentimentScorer = Depends(get_sentiment_scorer),
    cache: RedisCache = Depends(get_cache),
) -> dict[str, TickerSentiment]:
    """Batch sentiment scoring for multiple tickers."""
    import asyncio

    yf_client = YFinanceClient()
    news_agg = NewsAggregator(yf_client)
    aggregator = SentimentAggregator()

    async def fetch_one(symbol: str) -> tuple[str, TickerSentiment]:
        sym = symbol.upper()
        cached = await cache.get(f"sentiment:{sym}")
        if cached:
            return sym, TickerSentiment(**cached)
        articles = await news_agg.get_news(sym)
        texts = [(a.title + " " + (a.description or "")).strip() for a in articles if a.title]
        if not texts:
            from backend.scanner.scanner import _neutral_sentiment
            return sym, _neutral_sentiment(sym)
        results = await scorer.score_texts_async(texts)
        sentiment = aggregator.aggregate(sym, results, [a.title for a in articles[:5]])
        await cache.set(f"sentiment:{sym}", sentiment.model_dump(), get_settings().CACHE_TTL_SENTIMENT)
        return sym, sentiment

    tasks = [fetch_one(s) for s in symbols[:20]]  # cap at 20 symbols
    pairs = await asyncio.gather(*tasks, return_exceptions=True)
    return {sym: sent for sym, sent in pairs if not isinstance(sent, Exception)}
