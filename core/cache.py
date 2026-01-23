"""
Cache manager for Smart Money Dashboard.

Provides in-memory caching with optional Redis support
for distributed deployments.
"""

import asyncio
import hashlib
import json
import time
from typing import Any, Optional


class CacheManager:
    """
    Simple in-memory cache with TTL support.

    Usage:
        cache = CacheManager()
        await cache.set("key", {"data": "value"}, ttl=3600)
        value = await cache.get("key")
    """

    # Standard TTL values in seconds
    TTL_REALTIME = 60          # 1 minute - for live data
    TTL_SHORT = 900            # 15 minutes - for trades
    TTL_MEDIUM = 1800          # 30 minutes - for drill-down data
    TTL_HOURLY = 3600          # 1 hour - for netflow
    TTL_LONG = 7200            # 2 hours - for holdings

    def __init__(self):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def create(cls, use_redis: bool = False, redis_url: Optional[str] = None) -> "CacheManager":
        """
        Factory method to create appropriate cache instance.

        Args:
            use_redis: Whether to use Redis (currently not implemented)
            redis_url: Redis connection URL

        Returns:
            CacheManager instance
        """
        # For now, always return in-memory cache
        # Redis support can be added later if needed
        return cls()

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        async with self._lock:
            if key not in self._cache:
                return None

            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None

            return value

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """
        Set value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        """
        async with self._lock:
            expiry = time.time() + ttl
            self._cache[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        """Delete a key from cache."""
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        """Clear all cached values."""
        async with self._lock:
            self._cache.clear()

    async def cleanup_expired(self) -> int:
        """
        Remove expired entries from cache.

        Returns:
            Number of entries removed
        """
        async with self._lock:
            now = time.time()
            expired_keys = [
                key for key, (_, expiry) in self._cache.items()
                if now > expiry
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

    @staticmethod
    def make_key(*parts: str) -> str:
        """
        Create a cache key from parts.

        Args:
            parts: Key components to join

        Returns:
            Hashed cache key
        """
        key_str = ":".join(str(p) for p in parts)
        return hashlib.md5(key_str.encode()).hexdigest()

    def stats(self) -> dict:
        """Get cache statistics."""
        now = time.time()
        total = len(self._cache)
        expired = sum(1 for _, (_, exp) in self._cache.items() if now > exp)
        return {
            "total_entries": total,
            "expired_entries": expired,
            "active_entries": total - expired,
        }
