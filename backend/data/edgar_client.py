"""
SEC EDGAR client for fetching recent 8-K filings (free, no API key needed).
Used as supplementary news source for FinBERT sentiment analysis.
Respects EDGAR's 10 req/sec rate limit via asyncio.Semaphore.
"""

import asyncio
import logging
from datetime import date, timedelta

import httpx

from backend.models.sentiment import NewsArticle

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
HEADERS = {"User-Agent": "Leaps2.0 options-scanner research@example.com"}

_semaphore = asyncio.Semaphore(5)  # max 5 concurrent EDGAR requests


async def get_recent_filings(
    symbol: str, days_back: int = 14, form_types: list[str] | None = None
) -> list[NewsArticle]:
    """
    Fetch recent SEC EDGAR filings for a company ticker.
    Focuses on 8-K (current events) and 10-Q (quarterly) filings.
    Returns as NewsArticle objects for feeding into FinBERT.
    """
    if form_types is None:
        form_types = ["8-K", "10-Q"]

    start_date = (date.today() - timedelta(days=days_back)).isoformat()
    articles = []

    async with _semaphore:
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=15.0) as client:
                for form_type in form_types:
                    params = {
                        "q": f'"{symbol}"',
                        "dateRange": "custom",
                        "startdt": start_date,
                        "forms": form_type,
                        "_source": "hits.hits._source.period_of_report,"
                                   "hits.hits._source.entity_name,"
                                   "hits.hits._source.file_date,"
                                   "hits.hits._source.form_type,"
                                   "hits.hits._source.file_num",
                        "hits.hits.total.value": 5,
                    }
                    try:
                        resp = await client.get(
                            "https://efts.sec.gov/LATEST/search-index",
                            params={
                                "q": f'"{symbol}"',
                                "dateRange": "custom",
                                "startdt": start_date,
                                "forms": form_type,
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        hits = data.get("hits", {}).get("hits", [])
                        for hit in hits[:5]:
                            src = hit.get("_source", {})
                            entity = src.get("entity_name", symbol)
                            form = src.get("form_type", form_type)
                            filed = src.get("file_date", "")
                            articles.append(
                                NewsArticle(
                                    title=f"{entity} filed {form} ({filed})",
                                    description=f"SEC {form} filing by {entity}",
                                    url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                                        f"&company={symbol}&type={form_type}&dateb=&owner=include&count=10",
                                    published_at=filed,
                                    source="SEC EDGAR",
                                )
                            )
                    except Exception as e:
                        logger.debug("EDGAR %s fetch error for %s: %s", form_type, symbol, e)
        except Exception as e:
            logger.warning("EDGAR client error for %s: %s", symbol, e)

    return articles
