"""
Nansen API Client.

Async client for interacting with the Nansen API with
rate limiting and caching support.
"""

import asyncio
import os
from typing import Optional

import httpx

from .cache import CacheManager
from .nansen_models import (
    TokenHolding,
    TokenNetflow,
    DexTrade,
    TokenHolder,
    FlowIntelligence,
)


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, requests_per_minute: int = 400):
        self._requests_per_minute = requests_per_minute
        self._interval = 60.0 / requests_per_minute
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait if necessary to respect rate limit."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait_time = self._last_request + self._interval - now
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_request = asyncio.get_event_loop().time()


class NansenClient:
    """
    Async client for the Nansen API.

    Usage:
        async with NansenClient(api_key="your_key") as client:
            holdings = await client.get_smart_money_holdings("ethereum")
    """

    BASE_URL = "https://api.nansen.ai/api/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[CacheManager] = None,
        requests_per_minute: int = 400,
    ):
        self._api_key = api_key or os.environ.get("NANSEN_API_KEY")
        if not self._api_key:
            raise ValueError("NANSEN_API_KEY is required")

        self._cache = cache or CacheManager()
        self._rate_limiter = RateLimiter(requests_per_minute)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "NansenClient":
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "apikey": self._api_key,
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _post(
        self,
        endpoint: str,
        body: dict,
        cache_key: Optional[str] = None,
        cache_ttl: Optional[int] = None,
    ) -> dict:
        """
        Execute POST request with caching and rate limiting.

        Args:
            endpoint: API endpoint path
            body: Request body
            cache_key: Optional cache key
            cache_ttl: Cache TTL in seconds

        Returns:
            API response as dict
        """
        # Check cache first
        if cache_key:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # Rate limit
        await self._rate_limiter.acquire()

        # Make request
        if not self._client:
            raise RuntimeError("Client not initialized. Use async with context.")

        response = await self._client.post(
            f"{self.BASE_URL}{endpoint}",
            json=body,
        )
        response.raise_for_status()
        data = response.json()

        # Cache result
        if cache_key and data:
            await self._cache.set(cache_key, data, cache_ttl or CacheManager.TTL_HOURLY)

        return data

    # === Smart Money Endpoints ===

    async def get_smart_money_holdings(
        self,
        chains: list[str],
        limit: int = 100,
    ) -> list[TokenHolding]:
        """
        Get token holdings by smart money.

        Args:
            chains: List of blockchain networks
            limit: Maximum results to return

        Returns:
            List of TokenHolding objects
        """
        body = {
            "chains": chains,
            "pagination": {"page": 1, "per_page": limit},
        }

        cache_key = self._cache.make_key("nansen:holdings", ",".join(chains))
        data = await self._post(
            "/smart-money/holdings",
            body,
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_LONG,
        )

        return [
            TokenHolding.from_api_response(item)
            for item in data.get("data", [])
        ]

    async def get_smart_money_netflow(
        self,
        chains: list[str],
        limit: int = 100,
    ) -> list[TokenNetflow]:
        """
        Get netflow data for tokens.

        Args:
            chains: List of blockchain networks
            limit: Maximum results

        Returns:
            List of TokenNetflow objects
        """
        body = {
            "chains": chains,
            "pagination": {"page": 1, "per_page": limit},
        }

        cache_key = self._cache.make_key("nansen:netflow", ",".join(chains))
        data = await self._post(
            "/smart-money/netflow",
            body,
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_HOURLY,
        )

        return [
            TokenNetflow.from_api_response(item)
            for item in data.get("data", [])
        ]

    async def get_dex_trades(
        self,
        chains: list[str],
        limit: int = 100,
    ) -> list[DexTrade]:
        """
        Get recent DEX trades by smart money.

        Args:
            chains: List of blockchain networks
            limit: Maximum results

        Returns:
            List of DexTrade objects
        """
        body = {
            "chains": chains,
            "pagination": {"page": 1, "per_page": limit},
        }

        cache_key = self._cache.make_key("nansen:trades", ",".join(chains))
        data = await self._post(
            "/smart-money/dex-trades",
            body,
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_SHORT,
        )

        return [
            DexTrade.from_api_response(item)
            for item in data.get("data", [])
        ]

    # === Token God Mode Endpoints ===

    async def get_token_holders(
        self,
        token_address: str,
        chain: str,
        limit: int = 100,
    ) -> list[TokenHolder]:
        """
        Get holder breakdown for a specific token.

        Args:
            token_address: Token contract address
            chain: Blockchain network
            limit: Maximum results

        Returns:
            List of TokenHolder objects
        """
        body = {
            "token_address": token_address,
            "chain": chain,
            "pagination": {"page": 1, "per_page": limit},
        }

        cache_key = self._cache.make_key("nansen:tgm:holders", chain, token_address)
        data = await self._post(
            "/tgm/holders",
            body,
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_MEDIUM,
        )

        return [
            TokenHolder.from_api_response(item)
            for item in data.get("data", [])
        ]

    async def get_flow_intelligence(
        self,
        token_address: str,
        chain: str,
    ) -> FlowIntelligence:
        """
        Get flow intelligence by holder segment.

        Args:
            token_address: Token contract address
            chain: Blockchain network

        Returns:
            FlowIntelligence object
        """
        body = {
            "token_address": token_address,
            "chain": chain,
        }

        cache_key = self._cache.make_key("nansen:tgm:flows", chain, token_address)
        data = await self._post(
            "/tgm/flow-intelligence",
            body,
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_MEDIUM,
        )

        return FlowIntelligence.from_api_response(
            data.get("data", {}),
            token_address,
            chain,
        )

    async def get_who_bought_sold(
        self,
        token_address: str,
        chain: str,
        direction: str = "buy",
        limit: int = 50,
    ) -> list[dict]:
        """
        Get net buyers or sellers for a token.

        Args:
            token_address: Token contract address
            chain: Blockchain network
            direction: "buy" or "sell"
            limit: Maximum results

        Returns:
            List of buyer/seller records
        """
        body = {
            "token_address": token_address,
            "chain": chain,
            "direction": direction,
            "pagination": {"page": 1, "per_page": limit},
        }

        cache_key = self._cache.make_key("nansen:tgm:buysell", chain, token_address, direction)
        data = await self._post(
            "/tgm/who-bought-sold",
            body,
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_SHORT,
        )

        return data.get("data", [])

    async def get_perp_trades(
        self,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get perpetual trades from Hyperliquid by smart money.

        Returns:
            List of perp trade records
        """
        body = {
            "pagination": {"page": 1, "per_page": limit},
        }

        cache_key = self._cache.make_key("nansen:perp:trades")
        data = await self._post(
            "/smart-money/perp-trades",
            body,
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_SHORT,
        )

        return data.get("data", [])

