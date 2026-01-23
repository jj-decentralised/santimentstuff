"""In-memory TTL cache for API responses."""

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class CacheManager:
    """Simple TTL-based in-memory cache."""

    # TTL constants in seconds
    REALTIME = 60
    SHORT = 300  # 5 min
    MEDIUM = 900  # 15 min
    LONG = 3600  # 1 hour

    def __init__(self):
        self._cache: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.md5(key.encode()).hexdigest()

    async def get(self, key: str) -> Any | None:
        hashed = self._hash_key(key)
        async with self._lock:
            entry = self._cache.get(hashed)
            if entry is None:
                return None
            if time.time() > entry.expires_at:
                del self._cache[hashed]
                return None
            return entry.value

    async def set(self, key: str, value: Any, ttl: int = MEDIUM) -> None:
        hashed = self._hash_key(key)
        async with self._lock:
            self._cache[hashed] = CacheEntry(
                value=value,
                expires_at=time.time() + ttl,
            )

    async def delete(self, key: str) -> None:
        hashed = self._hash_key(key)
        async with self._lock:
            self._cache.pop(hashed, None)

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()

    async def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        now = time.time()
        removed = 0
        async with self._lock:
            expired_keys = [
                k for k, v in self._cache.items() if now > v.expires_at
            ]
            for k in expired_keys:
                del self._cache[k]
                removed += 1
        return removed

    def stats(self) -> dict:
        return {
            "entries": len(self._cache),
        }
