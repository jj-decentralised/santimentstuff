"""
Caching layer for Santiment API responses.

Uses Redis for distributed caching with fallback to in-memory cache.
"""

import asyncio
import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None
    REDIS_AVAILABLE = False


@dataclass
class CacheEntry:
    """A cached entry with metadata."""
    key: str
    value: Any
    created_at: float
    ttl_seconds: int

    @property
    def is_expired(self) -> bool:
        return time.time() > (self.created_at + self.ttl_seconds)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


class CacheBackend(ABC):
    """Abstract cache backend interface."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        pass

    @abstractmethod
    async def clear(self) -> None:
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        pass


class InMemoryCache(CacheBackend):
    """Simple in-memory cache for development/single instance."""

    def __init__(self, max_size: int = 10000):
        self._cache: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._cache[key]
                return None
            return entry.value

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        async with self._lock:
            # Evict oldest entries if at capacity
            if len(self._cache) >= self._max_size:
                # Remove expired entries first
                expired = [k for k, v in self._cache.items() if v.is_expired]
                for k in expired:
                    del self._cache[k]

                # If still at capacity, remove oldest
                if len(self._cache) >= self._max_size:
                    oldest_key = min(
                        self._cache.keys(),
                        key=lambda k: self._cache[k].created_at
                    )
                    del self._cache[oldest_key]

            self._cache[key] = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl_seconds=ttl_seconds
            )

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()

    async def exists(self, key: str) -> bool:
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired:
                del self._cache[key]
                return False
            return True

    @property
    def size(self) -> int:
        return len(self._cache)


class RedisCache(CacheBackend):
    """Redis-based distributed cache."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        key_prefix: str = "santiment:"
    ):
        if not REDIS_AVAILABLE:
            raise ImportError("redis package not installed")

        self._host = host
        self._port = port
        self._db = db
        self._password = password
        self._key_prefix = key_prefix
        self._client = None

    async def _get_client(self):
        if self._client is None:
            self._client = aioredis.Redis(
                host=self._host,
                port=self._port,
                db=self._db,
                password=self._password,
                decode_responses=True
            )
        return self._client

    def _make_key(self, key: str) -> str:
        return f"{self._key_prefix}{key}"

    async def get(self, key: str) -> Optional[Any]:
        client = await self._get_client()
        data = await client.get(self._make_key(key))
        if data is None:
            return None
        return json.loads(data)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        client = await self._get_client()
        await client.setex(
            self._make_key(key),
            ttl_seconds,
            json.dumps(value, default=str)
        )

    async def delete(self, key: str) -> None:
        client = await self._get_client()
        await client.delete(self._make_key(key))

    async def clear(self) -> None:
        client = await self._get_client()
        keys = await client.keys(f"{self._key_prefix}*")
        if keys:
            await client.delete(*keys)

    async def exists(self, key: str) -> bool:
        client = await self._get_client()
        return await client.exists(self._make_key(key)) > 0

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None


class CacheManager:
    """
    High-level cache manager with intelligent TTLs based on data type.

    Different data types have different freshness requirements:
    - Real-time prices: 30 seconds
    - Hourly metrics: 15 minutes
    - Daily metrics: 1 hour
    - Historical data: 24 hours
    - Static metadata: 7 days
    """

    # TTL configurations by data type (in seconds)
    TTL_REALTIME = 30
    TTL_HOURLY = 900  # 15 minutes
    TTL_DAILY = 3600  # 1 hour
    TTL_HISTORICAL = 86400  # 24 hours
    TTL_METADATA = 604800  # 7 days

    def __init__(self, backend: Optional[CacheBackend] = None):
        self._backend = backend or InMemoryCache()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
        }

    @staticmethod
    def _hash_key(*args, **kwargs) -> str:
        """Generate a deterministic cache key from arguments."""
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def make_key(self, namespace: str, *args, **kwargs) -> str:
        """Create a namespaced cache key."""
        hash_part = self._hash_key(*args, **kwargs)
        return f"{namespace}:{hash_part}"

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        value = await self._backend.get(key)
        if value is not None:
            self._stats["hits"] += 1
        else:
            self._stats["misses"] += 1
        return value

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Set a value in cache with optional TTL."""
        ttl = ttl_seconds or self.TTL_DAILY
        await self._backend.set(key, value, ttl)
        self._stats["sets"] += 1

    async def get_or_set(
        self,
        key: str,
        factory,
        ttl_seconds: Optional[int] = None
    ) -> Any:
        """Get from cache or compute and cache the value."""
        value = await self.get(key)
        if value is not None:
            return value

        # Compute the value
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()

        await self.set(key, value, ttl_seconds)
        return value

    async def invalidate(self, key: str) -> None:
        """Remove a key from cache."""
        await self._backend.delete(key)

    async def invalidate_namespace(self, namespace: str) -> None:
        """Remove all keys in a namespace (requires Redis)."""
        if isinstance(self._backend, RedisCache):
            client = await self._backend._get_client()
            keys = await client.keys(f"{self._backend._key_prefix}{namespace}:*")
            if keys:
                await client.delete(*keys)

    @property
    def stats(self) -> dict:
        """Get cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0
        return {
            **self._stats,
            "hit_rate": hit_rate,
        }

    @classmethod
    def create(cls, use_redis: bool = False) -> "CacheManager":
        """Factory method to create a cache manager."""
        if use_redis and REDIS_AVAILABLE:
            redis_url = os.environ.get("REDIS_URL", "localhost")
            redis_port = int(os.environ.get("REDIS_PORT", "6379"))
            redis_password = os.environ.get("REDIS_PASSWORD")
            backend = RedisCache(
                host=redis_url,
                port=redis_port,
                password=redis_password
            )
        else:
            backend = InMemoryCache()

        return cls(backend)
