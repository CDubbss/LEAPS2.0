"""
Redis-backed caching layer with JSON serialization.
Falls back to a simple in-process dict if Redis is unavailable.
"""

import json
import logging
from typing import Any, Callable, Awaitable

import redis.asyncio as aioredis
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Async Redis cache with JSON serialization.
    Supports both plain dicts and Pydantic models.
    """

    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client
        self._local_fallback: dict[str, str] = {}
        self._use_fallback = False

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(key)
            if raw:
                return json.loads(raw)
            return None
        except Exception:
            raw = self._local_fallback.get(key)
            return json.loads(raw) if raw else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if isinstance(value, BaseModel):
            serialized = value.model_dump_json()
        elif isinstance(value, list) and value and isinstance(value[0], BaseModel):
            serialized = json.dumps([v.model_dump() for v in value])
        else:
            serialized = json.dumps(value)

        try:
            await self._redis.setex(key, ttl, serialized)
        except Exception as e:
            logger.debug("Redis set failed (%s), using local fallback", e)
            self._local_fallback[key] = serialized

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        ttl: int,
    ) -> Any:
        """
        Cache-aside pattern:
        1. Try cache first
        2. On miss, call factory()
        3. Store result in cache with TTL
        4. Return result
        """
        cached = await self.get(key)
        if cached is not None:
            return cached

        value = await factory()
        await self.set(key, value, ttl)
        return value

    async def delete(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception:
            self._local_fallback.pop(key, None)

    async def ping(self) -> bool:
        try:
            return await self._redis.ping()
        except Exception:
            return False


async def create_cache(redis_url: str) -> RedisCache:
    """Create and return a RedisCache instance."""
    try:
        client = aioredis.from_url(redis_url, decode_responses=True)
        cache = RedisCache(client)
        if await cache.ping():
            logger.info("Redis connected at %s", redis_url)
        else:
            logger.warning("Redis ping failed — using in-process fallback cache")
        return cache
    except Exception as e:
        logger.warning("Redis connection failed (%s) — using in-process fallback cache", e)
        # Return cache with a dummy redis client that always fails → uses fallback
        return RedisCache(None)  # type: ignore[arg-type]
