"""Async client for Arkham Intelligence API."""

import asyncio
import os
import time
from typing import Any

import httpx

from .arkham_models import Fund, TokenHolding, Transfer, FlowData, FlowDataPoint
from .cache import CacheManager


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, burst: int = 1):
        self.rate = rate  # requests per second
        self.burst = burst
        self.tokens = burst
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class ArkhamClient:
    """Async client for Arkham Intelligence API."""

    BASE_URL = "https://api.arkm.com"

    # Known fund entity IDs
    KNOWN_FUNDS = [
        "a16z",
        "polychain-capital",
        "dragonfly-capital",
        "three-arrows-capital",
        "jump-trading",
        "galaxy-digital",
        "spartan-group",
        "animoca-brands",
        "electric-capital",
        "binance-labs",
        "paradigm",
        "sequoia-capital",
        "digital-currency-group",
        "blockchain-capital",
    ]

    def __init__(self, api_key: str | None = None, cache: CacheManager | None = None):
        self.api_key = api_key or os.environ.get("ARKHAM_API_KEY", "")
        self.cache = cache or CacheManager()
        self._client: httpx.AsyncClient | None = None

        # Rate limiters: standard (20/s) and heavy (1/s)
        self._standard_limiter = RateLimiter(rate=20, burst=5)
        self._heavy_limiter = RateLimiter(rate=1, burst=1)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"API-Key": self.api_key},
            timeout=30.0,
        )

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        endpoint: str,
        params: dict | None = None,
        heavy: bool = False,
        cache_ttl: int | None = None,
    ) -> Any:
        """Make an API request with rate limiting and caching."""
        if not self._client:
            raise RuntimeError("Client not connected. Use 'async with' or call connect().")

        # Check cache
        cache_key = f"{endpoint}:{params}"
        if cache_ttl:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                return cached

        # Rate limit
        limiter = self._heavy_limiter if heavy else self._standard_limiter
        await limiter.acquire()

        # Make request
        response = await self._client.get(endpoint, params=params)
        response.raise_for_status()

        data = response.json()

        # Cache result
        if cache_ttl:
            await self.cache.set(cache_key, data, cache_ttl)

        return data

    # === Entity Endpoints ===

    async def get_entity(self, entity_id: str) -> Fund | None:
        """Get entity information."""
        try:
            data = await self._request(
                f"/intelligence/entity/{entity_id}",
                cache_ttl=CacheManager.LONG,
            )
            return Fund.from_api(data)
        except httpx.HTTPStatusError:
            return None

    async def get_available_funds(self) -> list[Fund]:
        """Get all known funds that are available."""
        funds = []
        tasks = [self.get_entity(fund_id) for fund_id in self.KNOWN_FUNDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Fund) and result.type == "fund":
                funds.append(result)

        return funds

    # === Portfolio Endpoints ===

    async def get_portfolio(self, entity_id: str) -> list[TokenHolding]:
        """Get current portfolio holdings for an entity."""
        now_ms = int(time.time() * 1000)
        data = await self._request(
            f"/portfolio/entity/{entity_id}",
            params={"time": now_ms},
            cache_ttl=CacheManager.SHORT,
        )

        holdings = []
        for chain, tokens in data.items():
            if isinstance(tokens, dict):
                for token_id, token_data in tokens.items():
                    if isinstance(token_data, dict) and token_data.get("usd", 0) > 0:
                        holding = TokenHolding.from_api(chain, token_id, token_data)
                        holdings.append(holding)

        # Sort by USD value descending
        holdings.sort(key=lambda h: h.value_usd, reverse=True)
        return holdings

    # === Transfer Endpoints ===

    async def get_transfers(
        self,
        entity_id: str,
        limit: int = 100,
        chains: list[str] | None = None,
        sort_dir: str = "desc",
    ) -> list[Transfer]:
        """Get transfer history for an entity."""
        params = {
            "base": entity_id,
            "limit": limit,
            "sortDir": sort_dir,
        }
        if chains:
            params["chains"] = ",".join(chains)

        data = await self._request(
            "/transfers",
            params=params,
            heavy=True,
            cache_ttl=CacheManager.SHORT,
        )

        transfers = []
        for tx in data.get("transfers", []):
            transfer = Transfer.from_api(tx, entity_id)
            transfers.append(transfer)

        return transfers

    async def get_all_transfers(
        self,
        entity_id: str,
        token_symbol: str | None = None,
        max_transfers: int = 1000,
    ) -> list[Transfer]:
        """Get all transfers for an entity, paginating as needed."""
        all_transfers = []
        limit = 100

        while len(all_transfers) < max_transfers:
            transfers = await self.get_transfers(
                entity_id=entity_id,
                limit=limit,
                sort_dir="asc",  # Oldest first for cost basis
            )

            if not transfers:
                break

            for t in transfers:
                if token_symbol is None or t.token_symbol == token_symbol:
                    all_transfers.append(t)

            if len(transfers) < limit:
                break

            # Rate limit between pages
            await asyncio.sleep(1.1)

        return all_transfers

    # === Flow Endpoints ===

    async def get_flow(self, entity_id: str) -> dict[str, FlowData]:
        """Get historical flow data for an entity."""
        data = await self._request(
            f"/flow/entity/{entity_id}",
            cache_ttl=CacheManager.MEDIUM,
        )

        flows = {}
        for chain, points in data.items():
            if isinstance(points, list) and points:
                data_points = [FlowDataPoint.from_api(p) for p in points]
                flows[chain] = FlowData(chain=chain, data_points=data_points)

        return flows

    # === Aggregated Methods ===

    async def get_fund_summary(self, entity_id: str) -> dict:
        """Get a complete fund summary with holdings and basic info."""
        entity, holdings, flows = await asyncio.gather(
            self.get_entity(entity_id),
            self.get_portfolio(entity_id),
            self.get_flow(entity_id),
        )

        if not entity:
            return {"error": f"Entity {entity_id} not found"}

        total_value = sum(h.value_usd for h in holdings)
        total_inflow = sum(f.total_inflow for f in flows.values())
        total_outflow = sum(f.total_outflow for f in flows.values())

        return {
            "fund": entity,
            "holdings": holdings,
            "total_value_usd": total_value,
            "total_inflow": total_inflow,
            "total_outflow": total_outflow,
            "net_flow": total_inflow - total_outflow,
            "flows": flows,
        }
