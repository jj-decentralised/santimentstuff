"""
Santiment GraphQL API Client.

Async client for Santiment's API with rate limiting,
retry logic, and caching support.
"""

import asyncio
import os
import time
import logging
from typing import Optional, Any
from datetime import datetime, timezone

import httpx

from .cache import CacheManager

logger = logging.getLogger(__name__)


class SantimentRateLimiter:
    """Rate limiter respecting Santiment Pro limits: 600/min, 30K/hour."""

    def __init__(self, requests_per_minute: int = 180):
        self._rpm = requests_per_minute
        self._interval = 60.0 / requests_per_minute
        self._last_request = 0.0
        self._minute_count = 0
        self._minute_start = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Reset minute counter
            if now - self._minute_start >= 60.0:
                self._minute_count = 0
                self._minute_start = now
            # If at limit, wait until next minute
            if self._minute_count >= self._rpm:
                wait = 60.0 - (now - self._minute_start) + 0.1
                logger.info(f"Rate limit: waiting {wait:.1f}s")
                await asyncio.sleep(wait)
                self._minute_count = 0
                self._minute_start = time.monotonic()
            # Minimum spacing between requests
            elapsed = now - self._last_request
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            self._minute_count += 1
            self._last_request = time.monotonic()


class SantimentClient:
    """
    Async GraphQL client for Santiment API.

    Usage:
        async with SantimentClient(api_key="your_key") as client:
            data = await client.get_metric("daily_active_addresses", "bitcoin", "2024-01-01", "2024-12-01")
    """

    GRAPHQL_URL = "https://api.santiment.net/graphql"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[CacheManager] = None,
        requests_per_minute: int = 180,
    ):
        self._api_key = api_key or os.environ.get("SANTIMENT_API_KEY")
        if not self._api_key:
            raise ValueError("SANTIMENT_API_KEY is required")
        self._cache = cache or CacheManager()
        self._rate_limiter = SantimentRateLimiter(requests_per_minute)
        self._client: Optional[httpx.AsyncClient] = None
        # Stats tracking
        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "errors": 0,
            "retries": 0,
            "total_data_points": 0,
        }

    async def __aenter__(self) -> "SantimentClient":
        self._client = httpx.AsyncClient(
            timeout=60.0,
            headers={
                "Authorization": f"Apikey {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    async def _execute_graphql(
        self,
        query: str,
        variables: Optional[dict] = None,
        cache_key: Optional[str] = None,
        cache_ttl: Optional[int] = None,
        retries: int = 3,
    ) -> dict:
        """Execute a GraphQL query with caching, rate limiting, and retries."""
        # Check cache
        if cache_key:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                self._stats["cache_hits"] += 1
                return cached

        if not self._client:
            raise RuntimeError("Client not initialized. Use async with context.")

        last_error = None
        for attempt in range(retries):
            await self._rate_limiter.acquire()
            self._stats["total_requests"] += 1

            try:
                payload = {"query": query}
                if variables:
                    payload["variables"] = variables

                response = await self._client.post(self.GRAPHQL_URL, json=payload)

                # Log every non-200 response for debugging
                if response.status_code != 200:
                    body_preview = response.text[:500] if response.text else "(empty)"
                    logger.error(
                        f"Santiment HTTP {response.status_code} "
                        f"(attempt {attempt+1}/{retries}): {body_preview}"
                    )
                    self._stats["last_error"] = f"HTTP {response.status_code}: {body_preview[:200]}"

                if response.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"Rate limited (429). Waiting {wait}s...")
                    self._stats["errors"] += 1
                    self._stats["retries"] += 1
                    await asyncio.sleep(wait)
                    continue

                response.raise_for_status()
                data = response.json()

                if "errors" in data:
                    error_msg = data["errors"][0].get("message", "Unknown GraphQL error")
                    logger.error(f"GraphQL error: {error_msg}")
                    self._stats["errors"] += 1
                    self._stats["last_error"] = f"GraphQL: {error_msg}"
                    # Some errors are retryable
                    if "timeout" in error_msg.lower() or "rate" in error_msg.lower():
                        wait = 2 ** (attempt + 1)
                        self._stats["retries"] += 1
                        await asyncio.sleep(wait)
                        continue
                    return {"errors": data["errors"], "data": data.get("data")}

                result = data.get("data", {})

                # Cache result
                if cache_key and result:
                    await self._cache.set(cache_key, result, cache_ttl or CacheManager.TTL_HOURLY)

                return result

            except httpx.HTTPStatusError as e:
                last_error = e
                self._stats["errors"] += 1
                self._stats["last_error"] = f"HTTPStatusError {e.response.status_code}: {str(e)[:200]}"
                logger.error(f"HTTP error (attempt {attempt+1}/{retries}): {e}")
                if e.response.status_code >= 500:
                    wait = 2 ** (attempt + 1)
                    self._stats["retries"] += 1
                    await asyncio.sleep(wait)
                    continue
                raise
            except Exception as e:
                last_error = e
                self._stats["errors"] += 1
                self._stats["retries"] += 1
                self._stats["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
                wait = 2 ** (attempt + 1)
                logger.error(f"Request error (attempt {attempt+1}/{retries}), retry in {wait}s: {type(e).__name__}: {e}")
                await asyncio.sleep(wait)
                continue

        error_msg = f"All retries exhausted. Last error: {last_error}"
        self._stats["last_error"] = str(error_msg)[:300]
        raise RuntimeError(error_msg)

    # ================================================================
    # DISCOVERY: What metrics and slugs are available?
    # ================================================================

    async def get_all_available_metrics(self) -> list[str]:
        """Get every metric available on Santiment Pro."""
        query = """{ getAvailableMetrics }"""
        cache_key = self._cache.make_key("san:all_metrics")
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=86400)
        return result.get("getAvailableMetrics", [])

    async def get_all_projects(self) -> list[dict]:
        """Get all supported projects/tokens with their slugs."""
        query = """{
            allProjects {
                slug
                name
                ticker
                marketcapUsd
                infrastructure
            }
        }"""
        cache_key = self._cache.make_key("san:all_projects")
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=86400)
        return result.get("allProjects", [])

    async def get_metric_metadata(self, metric: str) -> dict:
        """Get metadata for a specific metric (min interval, available slugs, etc)."""
        query = """{
            getMetric(metric: "%s") {
                metadata {
                    minInterval
                    defaultAggregation
                    availableAggregations
                    dataType
                    isAccessible
                    isRestricted
                }
            }
        }""" % metric
        cache_key = self._cache.make_key("san:meta", metric)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=86400)
        meta = result.get("getMetric", {}).get("metadata", {})
        return meta

    async def get_available_slugs_for_metric(self, metric: str) -> list[str]:
        """Get all slugs that have data for a specific metric."""
        query = """{
            getMetric(metric: "%s") {
                metadata {
                    availableSlugs
                }
            }
        }""" % metric
        cache_key = self._cache.make_key("san:slugs", metric)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=86400)
        return result.get("getMetric", {}).get("metadata", {}).get("availableSlugs", [])

    async def get_project_available_metrics(self, slug: str) -> list[str]:
        """Get all metrics available for a specific project."""
        query = """{
            projectBySlug(slug: "%s") {
                availableMetrics
            }
        }""" % slug
        cache_key = self._cache.make_key("san:proj_metrics", slug)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=86400)
        return result.get("projectBySlug", {}).get("availableMetrics", [])

    # ================================================================
    # TIMESERIES DATA: The main data pull
    # ================================================================

    async def get_metric_timeseries(
        self,
        metric: str,
        slug: str,
        from_date: str,
        to_date: str,
        interval: str = "1d",
        aggregation: Optional[str] = None,
    ) -> list[dict]:
        """
        Get timeseries data for a metric.

        Returns list of {"datetime": "...", "value": ...} dicts.
        """
        agg_clause = f', aggregation: {aggregation}' if aggregation else ''
        query = """{
            getMetric(metric: "%s") {
                timeseriesData(
                    slug: "%s"
                    from: "%s"
                    to: "%s"
                    interval: "%s"
                    %s
                ) {
                    datetime
                    value
                }
            }
        }""" % (metric, slug, from_date, to_date, interval, agg_clause)

        cache_key = self._cache.make_key("san:ts", metric, slug, from_date, to_date, interval)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=CacheManager.TTL_LONG)

        data = result.get("getMetric", {}).get("timeseriesData", [])
        if data:
            self._stats["total_data_points"] += len(data)
        return data or []

    async def get_metric_timeseries_json(
        self,
        metric: str,
        slug: str,
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> list[dict]:
        """
        Get timeseries data using the JSON variant (faster for large datasets).
        """
        query = """{
            getMetric(metric: "%s") {
                timeseriesDataJson(
                    slug: "%s"
                    from: "%s"
                    to: "%s"
                    interval: "%s"
                )
            }
        }""" % (metric, slug, from_date, to_date, interval)

        cache_key = self._cache.make_key("san:tsj", metric, slug, from_date, to_date, interval)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=CacheManager.TTL_LONG)

        import json as _json
        raw = result.get("getMetric", {}).get("timeseriesDataJson", "[]")
        if isinstance(raw, str):
            data = _json.loads(raw)
        else:
            data = raw or []
        if data:
            self._stats["total_data_points"] += len(data)
        return data

    async def get_metric_aggregated(
        self,
        metric: str,
        slug: str,
        from_date: str,
        to_date: str,
        aggregation: str = "LAST",
    ) -> Optional[float]:
        """Get a single aggregated value for a metric over a time range."""
        query = """{
            getMetric(metric: "%s") {
                aggregatedTimeseriesData(
                    slug: "%s"
                    from: "%s"
                    to: "%s"
                    aggregation: %s
                )
            }
        }""" % (metric, slug, from_date, to_date, aggregation)

        cache_key = self._cache.make_key("san:agg", metric, slug, from_date, to_date, aggregation)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=CacheManager.TTL_HOURLY)
        return result.get("getMetric", {}).get("aggregatedTimeseriesData")

    # ================================================================
    # BATCH QUERIES: Pull multiple metrics in one request
    # ================================================================

    async def get_multiple_metrics_for_slug(
        self,
        metrics: list[str],
        slug: str,
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> dict[str, list[dict]]:
        """
        Batch multiple metrics for one slug in a single GraphQL request.
        Returns {metric_name: [data_points]}.
        """
        # Build aliased sub-queries
        parts = []
        for i, metric in enumerate(metrics):
            alias = f"m{i}"
            parts.append(f"""
                {alias}: getMetric(metric: "{metric}") {{
                    timeseriesData(
                        slug: "{slug}"
                        from: "{from_date}"
                        to: "{to_date}"
                        interval: "{interval}"
                    ) {{
                        datetime
                        value
                    }}
                }}
            """)

        query = "{\n" + "\n".join(parts) + "\n}"
        cache_key = self._cache.make_key("san:batch", slug, ",".join(metrics), from_date, to_date, interval)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=CacheManager.TTL_LONG)

        output = {}
        for i, metric in enumerate(metrics):
            alias = f"m{i}"
            data = result.get(alias, {}).get("timeseriesData", [])
            output[metric] = data or []
            self._stats["total_data_points"] += len(data) if data else 0

        return output

    # ================================================================
    # SPECIAL QUERIES: Non-getMetric endpoints
    # ================================================================

    async def get_ohlcv(
        self,
        slug: str,
        from_date: str,
        to_date: str,
        interval: str = "1d",
    ) -> list[dict]:
        """Get OHLCV price data."""
        query = """{
            ohlcv(
                slug: "%s"
                from: "%s"
                to: "%s"
                interval: "%s"
            ) {
                datetime
                openPriceUsd
                closePriceUsd
                highPriceUsd
                lowPriceUsd
                volume
                marketcap
            }
        }""" % (slug, from_date, to_date, interval)

        cache_key = self._cache.make_key("san:ohlcv", slug, from_date, to_date, interval)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=CacheManager.TTL_LONG)
        data = result.get("ohlcv", [])
        self._stats["total_data_points"] += len(data) if data else 0
        return data or []

    async def get_top_transfers(
        self,
        slug: str,
        from_date: str,
        to_date: str,
        limit: int = 20,
    ) -> list[dict]:
        """Get top token transfers."""
        query = """{
            topTransfers(
                slug: "%s"
                from: "%s"
                to: "%s"
                limit: %d
            ) {
                datetime
                fromAddress { address isExchange }
                toAddress { address isExchange }
                trxValue
                trxHash
            }
        }""" % (slug, from_date, to_date, limit)

        cache_key = self._cache.make_key("san:transfers", slug, from_date, to_date)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=CacheManager.TTL_MEDIUM)
        return result.get("topTransfers", [])

    async def get_emerging_trends(self) -> list[dict]:
        """Get current emerging trends in crypto social media."""
        query = """{
            getTrendingWords(
                source: ALL
                size: 20
            ) {
                datetime
                topWords {
                    word
                    score
                }
            }
        }"""
        cache_key = self._cache.make_key("san:trends")
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=CacheManager.TTL_SHORT)
        return result.get("getTrendingWords", [])

    async def get_project_fundamentals(self, slug: str) -> dict:
        """Get project fundamental data."""
        query = """{
            projectBySlug(slug: "%s") {
                slug
                name
                ticker
                description
                websiteLink
                marketcapUsd
                infrastructure
                mainContractAddress
                totalSupply
                devActivity30: averageDevActivity(days: 30)
                devActivity90: averageDevActivity(days: 90)
            }
        }""" % slug

        cache_key = self._cache.make_key("san:fundamentals", slug)
        result = await self._execute_graphql(query, cache_key=cache_key, cache_ttl=CacheManager.TTL_LONG)
        return result.get("projectBySlug", {})
