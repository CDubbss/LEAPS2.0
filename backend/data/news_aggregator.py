"""
Aggregates news from yfinance and SEC EDGAR into a single list per ticker.
All sources are free and require no API keys.
"""

import asyncio
import logging

from backend.data.edgar_client import get_recent_filings
from backend.data.yfinance_client import YFinanceClient
from backend.models.sentiment import NewsArticle

logger = logging.getLogger(__name__)


class NewsAggregator:
    """
    Combines news from:
    1. yfinance ticker.news  (Yahoo Finance news feed)
    2. SEC EDGAR 8-K filings (material events, earnings)
    """

    def __init__(self, yf_client: YFinanceClient):
        self.yf_client = yf_client

    async def get_news(self, symbol: str, max_articles: int = 25) -> list[NewsArticle]:
        """
        Fetch and deduplicate news from all sources.
        Returns up to max_articles, sorted by recency.
        """
        yf_task = self.yf_client.get_news(symbol)
        edgar_task = get_recent_filings(symbol, days_back=14)

        results = await asyncio.gather(yf_task, edgar_task, return_exceptions=True)

        all_articles: list[NewsArticle] = []
        for result in results:
            if isinstance(result, Exception):
                logger.debug("News fetch error: %s", result)
                continue
            all_articles.extend(result)

        # Deduplicate by title
        seen_titles: set[str] = set()
        unique = []
        for article in all_articles:
            key = article.title.lower()[:80]
            if key not in seen_titles and article.title:
                seen_titles.add(key)
                unique.append(article)

        return unique[:max_articles]

    async def get_news_batch(
        self, symbols: list[str]
    ) -> dict[str, list[NewsArticle]]:
        """Fetch news for multiple symbols concurrently."""
        tasks = {symbol: self.get_news(symbol) for symbol in symbols}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        output = {}
        for symbol, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning("News batch error for %s: %s", symbol, result)
                output[symbol] = []
            else:
                output[symbol] = result
        return output
