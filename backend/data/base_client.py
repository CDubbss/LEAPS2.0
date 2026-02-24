import asyncio
import logging
from abc import ABC

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class BaseAPIClient(ABC):
    """
    Abstract async HTTP client with retry logic.
    Use as async context manager or call open()/close() manually.
    """

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def open(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *args):
        await self.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _get(self, path: str, params: dict | None = None) -> dict:
        if self._client is None:
            # Lazy open — supports calling without explicit context manager
            await self.open()
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error %s for %s: %s", e.response.status_code, path, e)
            raise
        except httpx.RequestError as e:
            logger.error("Request error for %s: %s", path, e)
            raise
