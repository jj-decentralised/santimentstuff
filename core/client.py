"""
Santiment GraphQL API Client.

Provides async access to all Santiment metrics with caching and rate limiting.
"""

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from .cache import CacheManager
from .models import (
    Asset,
    DevActivity,
    ExchangeFlow,
    HolderDistribution,
    HolderLabel,
    Metric,
    NetworkMetrics,
    SentimentData,
    TimeseriesData,
    TrendingWord,
    ValuationMetrics,
    WhaleTransaction,
)


class RateLimiter:
    """Simple rate limiter for API requests."""

    def __init__(self, requests_per_minute: int = 100):
        self._requests_per_minute = requests_per_minute
        self._requests: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until we can make a request."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            # Remove requests older than 1 minute
            self._requests = [t for t in self._requests if now - t < 60]

            if len(self._requests) >= self._requests_per_minute:
                # Wait until the oldest request is 1 minute old
                sleep_time = 60 - (now - self._requests[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            self._requests.append(now)


class SantimentAPIError(Exception):
    """Santiment API error."""

    def __init__(self, message: str, errors: Optional[list] = None):
        super().__init__(message)
        self.errors = errors or []


class SantimentClient:
    """
    Async client for the Santiment GraphQL API.

    Usage:
        async with SantimentClient(api_key="...") as client:
            data = await client.get_metric("bitcoin", "daily_active_addresses")
    """

    API_URL = "https://api.santiment.net/graphql"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[CacheManager] = None,
        requests_per_minute: int = 100,
    ):
        self._api_key = api_key or os.environ.get("SANTIMENT_API_KEY")
        self._cache = cache or CacheManager.create()
        self._rate_limiter = RateLimiter(requests_per_minute)
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers=self._get_headers(),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    def _get_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Apikey {self._api_key}"
        return headers

    async def _execute_query(
        self,
        query: str,
        variables: Optional[dict] = None,
        cache_key: Optional[str] = None,
        cache_ttl: Optional[int] = None,
    ) -> dict:
        """Execute a GraphQL query with caching and rate limiting."""

        # Check cache first
        if cache_key:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        # Rate limit
        await self._rate_limiter.acquire()

        # Execute query
        if self._client is None:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        response = await self._client.post(
            self.API_URL,
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        result = response.json()

        if "errors" in result:
            raise SantimentAPIError(
                f"GraphQL errors: {result['errors']}",
                errors=result["errors"]
            )

        data = result.get("data", {})

        # Cache the result
        if cache_key and data:
            await self._cache.set(cache_key, data, cache_ttl or CacheManager.TTL_DAILY)

        return data

    # ==================== Asset Methods ====================

    async def get_all_assets(self) -> list[Asset]:
        """Get all available assets."""
        query = """
        query {
            allProjects {
                slug
                name
                ticker
                marketcapUsd
                infrastructure
            }
        }
        """
        cache_key = self._cache.make_key("assets", "all")
        data = await self._execute_query(
            query, cache_key=cache_key, cache_ttl=CacheManager.TTL_METADATA
        )

        return [
            Asset(
                slug=p["slug"],
                name=p["name"],
                ticker=p["ticker"] or "",
                market_cap_usd=p.get("marketcapUsd"),
                infrastructure=p.get("infrastructure"),
            )
            for p in data.get("allProjects", [])
        ]

    async def get_asset(self, slug: str) -> Optional[Asset]:
        """Get a specific asset by slug."""
        query = """
        query($slug: String!) {
            projectBySlug(slug: $slug) {
                slug
                name
                ticker
                marketcapUsd
                infrastructure
            }
        }
        """
        cache_key = self._cache.make_key("asset", slug)
        data = await self._execute_query(
            query,
            variables={"slug": slug},
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_METADATA,
        )

        p = data.get("projectBySlug")
        if not p:
            return None

        return Asset(
            slug=p["slug"],
            name=p["name"],
            ticker=p["ticker"] or "",
            market_cap_usd=p.get("marketcapUsd"),
            infrastructure=p.get("infrastructure"),
        )

    # ==================== Generic Metric Methods ====================

    async def get_metric(
        self,
        slug: str,
        metric: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
    ) -> list[TimeseriesData]:
        """
        Get timeseries data for any metric.

        Args:
            slug: Asset slug (e.g., "bitcoin", "ethereum")
            metric: Metric name (e.g., "daily_active_addresses", "mvrv_usd")
            from_date: Start date
            to_date: End date
            interval: Data interval ("1h", "1d", "1w")
        """
        query = """
        query($metric: String!, $slug: String!, $from: DateTime!, $to: DateTime!, $interval: interval!) {
            getMetric(metric: $metric) {
                timeseriesData(slug: $slug, from: $from, to: $to, interval: $interval) {
                    datetime
                    value
                }
            }
        }
        """

        cache_key = self._cache.make_key(
            "metric", metric, slug, from_date.isoformat(), to_date.isoformat(), interval
        )

        data = await self._execute_query(
            query,
            variables={
                "metric": metric,
                "slug": slug,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "interval": interval,
            },
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_DAILY if to_date < datetime.now() - timedelta(days=1) else CacheManager.TTL_HOURLY,
        )

        timeseries = data.get("getMetric", {}).get("timeseriesData", [])
        return [
            TimeseriesData(
                datetime=datetime.fromisoformat(d["datetime"].replace("Z", "+00:00")),
                value=d["value"],
                metric=metric,
                asset_slug=slug,
            )
            for d in timeseries
            if d.get("value") is not None
        ]

    async def get_available_metrics(self, slug: str) -> list[str]:
        """Get list of available metrics for an asset."""
        query = """
        query($slug: String!) {
            projectBySlug(slug: $slug) {
                availableMetrics
            }
        }
        """
        cache_key = self._cache.make_key("available_metrics", slug)
        data = await self._execute_query(
            query,
            variables={"slug": slug},
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_METADATA,
        )
        return data.get("projectBySlug", {}).get("availableMetrics", [])

    # ==================== Price Methods ====================

    async def get_price(
        self,
        slug: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
    ) -> list[dict]:
        """Get OHLC price data."""
        query = """
        query($slug: String!, $from: DateTime!, $to: DateTime!, $interval: interval!) {
            ohlc(slug: $slug, from: $from, to: $to, interval: $interval) {
                datetime
                openPriceUsd
                highPriceUsd
                lowPriceUsd
                closePriceUsd
                volume
            }
        }
        """

        cache_key = self._cache.make_key(
            "ohlc", slug, from_date.isoformat(), to_date.isoformat(), interval
        )

        data = await self._execute_query(
            query,
            variables={
                "slug": slug,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "interval": interval,
            },
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_HOURLY,
        )

        return data.get("ohlc", [])

    # ==================== Whale & Exchange Flow Methods ====================

    async def get_whale_transactions(
        self,
        slug: str,
        from_date: datetime,
        to_date: datetime,
        min_value_usd: float = 100000,
    ) -> list[WhaleTransaction]:
        """Get large transactions (whale movements)."""
        query = """
        query($slug: String!, $from: DateTime!, $to: DateTime!) {
            getMetric(metric: "whale_transaction_count_100k_usd_to_inf") {
                timeseriesData(slug: $slug, from: $from, to: $to, interval: "1d") {
                    datetime
                    value
                }
            }
        }
        """

        cache_key = self._cache.make_key(
            "whale_tx", slug, from_date.isoformat(), to_date.isoformat()
        )

        # For whale transactions, we also need top transactions data
        top_tx_query = """
        query($slug: String!, $from: DateTime!, $to: DateTime!) {
            projectBySlug(slug: $slug) {
                ethTopTransfers(from: $from, to: $to) {
                    datetime
                    fromAddress { address isExchange }
                    toAddress { address isExchange }
                    trxValue
                    trxHash
                }
            }
        }
        """

        # Get count data
        count_data = await self._execute_query(
            query,
            variables={
                "slug": slug,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            },
            cache_key=cache_key,
        )

        # Also try to get actual transactions for ERC-20 tokens
        transactions = []
        try:
            tx_data = await self._execute_query(
                top_tx_query,
                variables={
                    "slug": slug,
                    "from": from_date.isoformat(),
                    "to": to_date.isoformat(),
                },
            )

            for tx in tx_data.get("projectBySlug", {}).get("ethTopTransfers", []):
                from_is_exchange = tx.get("fromAddress", {}).get("isExchange", False)
                to_is_exchange = tx.get("toAddress", {}).get("isExchange", False)

                transactions.append(
                    WhaleTransaction(
                        datetime=datetime.fromisoformat(tx["datetime"].replace("Z", "+00:00")),
                        asset_slug=slug,
                        from_address=tx.get("fromAddress", {}).get("address", ""),
                        to_address=tx.get("toAddress", {}).get("address", ""),
                        value=tx.get("trxValue", 0),
                        value_usd=tx.get("trxValue", 0),  # Would need price conversion
                        tx_hash=tx.get("trxHash", ""),
                        from_label=HolderLabel.EXCHANGE if from_is_exchange else HolderLabel.UNKNOWN,
                        to_label=HolderLabel.EXCHANGE if to_is_exchange else HolderLabel.UNKNOWN,
                        is_exchange_deposit=to_is_exchange and not from_is_exchange,
                        is_exchange_withdrawal=from_is_exchange and not to_is_exchange,
                    )
                )
        except Exception:
            pass  # Not all assets support top transfers

        return transactions

    async def get_exchange_flow(
        self,
        slug: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
    ) -> list[ExchangeFlow]:
        """Get exchange inflow/outflow data."""
        # Fetch both inflow and outflow
        inflow_data = await self.get_metric(
            slug, "exchange_inflow", from_date, to_date, interval
        )
        outflow_data = await self.get_metric(
            slug, "exchange_outflow", from_date, to_date, interval
        )

        # Merge by datetime
        outflow_map = {d.datetime: d.value for d in outflow_data}

        flows = []
        for inflow in inflow_data:
            outflow = outflow_map.get(inflow.datetime, 0)
            flows.append(
                ExchangeFlow(
                    datetime=inflow.datetime,
                    asset_slug=slug,
                    inflow=inflow.value,
                    outflow=outflow,
                    net_flow=inflow.value - outflow,
                )
            )

        return flows

    # ==================== Holder Distribution Methods ====================

    async def get_holder_distribution(
        self,
        slug: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[HolderDistribution]:
        """Get token holder distribution by balance tiers."""
        tiers = [
            "0-0.001", "0.001-0.01", "0.01-0.1", "0.1-1", "1-10",
            "10-100", "100-1k", "1k-10k", "10k-100k", "100k-1M",
            "1M-10M", "10M-inf"
        ]

        distributions = []
        for tier in tiers:
            metric = f"holders_distribution_{tier.replace('-', '_to_')}"
            try:
                data = await self.get_metric(slug, metric, from_date, to_date, "1d")
                for d in data:
                    distributions.append(
                        HolderDistribution(
                            asset_slug=slug,
                            datetime=d.datetime,
                            tier=tier,
                            holder_count=int(d.value),
                            total_balance=0,  # Would need separate query
                            percent_of_supply=0,
                        )
                    )
            except Exception:
                continue  # Tier not available for this asset

        return distributions

    async def get_top_holders(
        self,
        slug: str,
        count: int = 100,
    ) -> list[dict]:
        """Get top token holders."""
        query = """
        query($slug: String!, $count: Int!) {
            topHolders(slug: $slug, count: $count) {
                address
                balance
                balanceChange1d
                balanceChange7d
                balanceChange30d
            }
        }
        """

        cache_key = self._cache.make_key("top_holders", slug, count)
        data = await self._execute_query(
            query,
            variables={"slug": slug, "count": count},
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_HOURLY,
        )

        return data.get("topHolders", [])

    # ==================== Social & Sentiment Methods ====================

    async def get_sentiment(
        self,
        slug: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
    ) -> list[SentimentData]:
        """Get social sentiment data."""
        # Fetch multiple sentiment metrics
        metrics = [
            "sentiment_balance_total",
            "sentiment_volume_consumed_total",
            "social_volume_total",
            "social_dominance_total",
        ]

        results = await asyncio.gather(
            *[self.get_metric(slug, m, from_date, to_date, interval) for m in metrics],
            return_exceptions=True
        )

        # Build sentiment data by combining metrics
        sentiment_map: dict[datetime, dict] = {}
        for metric, data in zip(metrics, results):
            if isinstance(data, Exception):
                continue
            for d in data:
                if d.datetime not in sentiment_map:
                    sentiment_map[d.datetime] = {"datetime": d.datetime}
                sentiment_map[d.datetime][metric] = d.value

        return [
            SentimentData(
                datetime=data["datetime"],
                asset_slug=slug,
                sentiment_score=data.get("sentiment_balance_total", 0),
                sentiment_weighted=data.get("sentiment_volume_consumed_total", 0),
                social_volume=int(data.get("social_volume_total", 0)),
                social_dominance=data.get("social_dominance_total", 0),
                positive_mentions=0,
                negative_mentions=0,
            )
            for data in sentiment_map.values()
        ]

    async def get_trending_words(
        self,
        hours: int = 24,
        size: int = 10,
    ) -> list[TrendingWord]:
        """Get trending words in crypto social media."""
        query = """
        query($from: DateTime!, $to: DateTime!, $size: Int!) {
            getTrendingWords(from: $from, to: $to, size: $size) {
                datetime
                topWords {
                    word
                    score
                }
            }
        }
        """

        to_date = datetime.utcnow()
        from_date = to_date - timedelta(hours=hours)

        cache_key = self._cache.make_key("trending", hours, size)
        data = await self._execute_query(
            query,
            variables={
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "size": size,
            },
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_HOURLY,
        )

        words = []
        for entry in data.get("getTrendingWords", []):
            dt = datetime.fromisoformat(entry["datetime"].replace("Z", "+00:00"))
            for w in entry.get("topWords", []):
                words.append(
                    TrendingWord(
                        word=w["word"],
                        hype_score=w.get("score", 0),
                        social_volume=0,
                        unique_authors=0,
                        hour=dt,
                    )
                )

        return words

    # ==================== Development Activity Methods ====================

    async def get_dev_activity(
        self,
        slug: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
    ) -> list[DevActivity]:
        """Get development activity metrics."""
        metrics = ["dev_activity", "dev_activity_contributors_count"]

        results = await asyncio.gather(
            *[self.get_metric(slug, m, from_date, to_date, interval) for m in metrics],
            return_exceptions=True
        )

        # Build dev activity data
        activity_map: dict[datetime, dict] = {}
        for metric, data in zip(metrics, results):
            if isinstance(data, Exception):
                continue
            for d in data:
                if d.datetime not in activity_map:
                    activity_map[d.datetime] = {"datetime": d.datetime}
                activity_map[d.datetime][metric] = d.value

        return [
            DevActivity(
                datetime=data["datetime"],
                asset_slug=slug,
                dev_activity=data.get("dev_activity", 0),
                dev_activity_contributors=int(data.get("dev_activity_contributors_count", 0)),
                github_activity=data.get("dev_activity", 0),
                contributors_count=int(data.get("dev_activity_contributors_count", 0)),
            )
            for data in activity_map.values()
        ]

    # ==================== Valuation Methods ====================

    async def get_valuation_metrics(
        self,
        slug: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
    ) -> list[ValuationMetrics]:
        """Get on-chain valuation metrics (MVRV, NVT)."""
        metrics = ["mvrv_usd", "mvrv_long_short_diff_usd", "nvt", "realized_value_usd", "marketcap_usd"]

        results = await asyncio.gather(
            *[self.get_metric(slug, m, from_date, to_date, interval) for m in metrics],
            return_exceptions=True
        )

        # Build valuation data
        val_map: dict[datetime, dict] = {}
        for metric, data in zip(metrics, results):
            if isinstance(data, Exception):
                continue
            for d in data:
                if d.datetime not in val_map:
                    val_map[d.datetime] = {"datetime": d.datetime}
                val_map[d.datetime][metric] = d.value

        return [
            ValuationMetrics(
                datetime=data["datetime"],
                asset_slug=slug,
                mvrv_ratio=data.get("mvrv_usd", 1),
                mvrv_long_short_diff=data.get("mvrv_long_short_diff_usd"),
                nvt_ratio=data.get("nvt"),
                realized_cap=data.get("realized_value_usd"),
                market_cap=data.get("marketcap_usd"),
            )
            for data in val_map.values()
        ]

    # ==================== Network Metrics Methods ====================

    async def get_network_metrics(
        self,
        slug: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
    ) -> list[NetworkMetrics]:
        """Get on-chain network activity metrics."""
        metrics = [
            "daily_active_addresses",
            "network_growth",
            "transaction_volume",
            "velocity",
            "age_consumed",
            "network_profit_loss",
        ]

        results = await asyncio.gather(
            *[self.get_metric(slug, m, from_date, to_date, interval) for m in metrics],
            return_exceptions=True
        )

        # Build network metrics data
        net_map: dict[datetime, dict] = {}
        for metric, data in zip(metrics, results):
            if isinstance(data, Exception):
                continue
            for d in data:
                if d.datetime not in net_map:
                    net_map[d.datetime] = {"datetime": d.datetime}
                net_map[d.datetime][metric] = d.value

        return [
            NetworkMetrics(
                datetime=data["datetime"],
                asset_slug=slug,
                daily_active_addresses=int(data.get("daily_active_addresses", 0)),
                network_growth=int(data.get("network_growth", 0)),
                transaction_volume=data.get("transaction_volume", 0),
                velocity=data.get("velocity", 0),
                token_age_consumed=data.get("age_consumed", 0),
                realized_profit_loss=data.get("network_profit_loss"),
            )
            for data in net_map.values()
        ]

    # ==================== Utility Methods ====================

    async def get_metric_metadata(self, metric: str) -> Optional[Metric]:
        """Get metadata about a metric."""
        query = """
        query($metric: String!) {
            getMetric(metric: $metric) {
                metadata {
                    metric
                    humanReadableName
                    minInterval
                    defaultAggregation
                    isAccessible
                    isRestricted
                }
            }
        }
        """

        cache_key = self._cache.make_key("metric_meta", metric)
        data = await self._execute_query(
            query,
            variables={"metric": metric},
            cache_key=cache_key,
            cache_ttl=CacheManager.TTL_METADATA,
        )

        meta = data.get("getMetric", {}).get("metadata")
        if not meta:
            return None

        return Metric(
            name=meta.get("metric", metric),
            description=meta.get("humanReadableName", ""),
            min_interval=meta.get("minInterval", "1d"),
            default_aggregation=meta.get("defaultAggregation", "AVG"),
            is_restricted=meta.get("isRestricted", False),
        )
