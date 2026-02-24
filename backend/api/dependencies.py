"""
FastAPI dependency injection functions.
All expensive objects (FinBERT, ML model, Redis) live in app.state,
loaded once during startup via the lifespan context manager.
"""

from fastapi import Request

from backend.api.cache import RedisCache
from backend.config.settings import Settings, get_settings
from backend.data.fmp_client import FMPClient
from backend.data.news_aggregator import NewsAggregator
from backend.data.yfinance_client import YFinanceClient
from backend.ml.model import SpreadRanker
from backend.scanner.scanner import OptionsScanner
from backend.sentiment.aggregator import SentimentAggregator
from backend.sentiment.finbert_loader import FinBERTLoader
from backend.sentiment.sentiment_scorer import SentimentScorer


def get_settings_dep() -> Settings:
    return get_settings()


def get_cache(request: Request) -> RedisCache:
    return request.app.state.cache


def get_finbert_loader(request: Request) -> FinBERTLoader:
    return request.app.state.finbert_loader


def get_ml_ranker(request: Request) -> SpreadRanker:
    return request.app.state.ml_ranker


def get_yf_client() -> YFinanceClient:
    return YFinanceClient()


def get_fmp_client() -> FMPClient:
    settings = get_settings()
    return FMPClient(api_key=settings.FMP_API_KEY)


def get_sentiment_scorer(request: Request) -> SentimentScorer:
    return SentimentScorer(request.app.state.finbert_loader)


def get_scanner(request: Request) -> OptionsScanner:
    """Build and return the scanner with all injected dependencies."""
    settings = get_settings()
    yf_client = YFinanceClient()
    fmp_client = FMPClient(api_key=settings.FMP_API_KEY)
    news_agg = NewsAggregator(yf_client)
    sent_scorer = SentimentScorer(request.app.state.finbert_loader)
    sent_agg = SentimentAggregator()
    ml_ranker = request.app.state.ml_ranker
    cache = request.app.state.cache

    return OptionsScanner(
        yf_client=yf_client,
        fmp_client=fmp_client,
        news_aggregator=news_agg,
        sentiment_scorer=sent_scorer,
        sentiment_aggregator=sent_agg,
        ml_ranker=ml_ranker,
        cache=cache,
        settings=settings,
    )
