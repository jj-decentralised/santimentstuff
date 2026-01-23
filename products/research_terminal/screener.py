"""
Asset Screener

Powerful screening capabilities to filter and rank assets
based on multiple criteria across all data dimensions.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Any

from core.client import SantimentClient


class FilterOperator(Enum):
    """Filter comparison operators."""
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    GREATER_EQUAL = "gte"
    LESS_EQUAL = "lte"
    EQUAL = "eq"
    NOT_EQUAL = "neq"
    BETWEEN = "between"
    IN = "in"


@dataclass
class ScreenerFilter:
    """A single screening filter."""
    metric: str
    operator: FilterOperator
    value: Any
    value_max: Optional[Any] = None  # For BETWEEN operator

    def evaluate(self, actual_value: Any) -> bool:
        """Evaluate if the actual value passes this filter."""
        if actual_value is None:
            return False

        if self.operator == FilterOperator.GREATER_THAN:
            return actual_value > self.value
        elif self.operator == FilterOperator.LESS_THAN:
            return actual_value < self.value
        elif self.operator == FilterOperator.GREATER_EQUAL:
            return actual_value >= self.value
        elif self.operator == FilterOperator.LESS_EQUAL:
            return actual_value <= self.value
        elif self.operator == FilterOperator.EQUAL:
            return actual_value == self.value
        elif self.operator == FilterOperator.NOT_EQUAL:
            return actual_value != self.value
        elif self.operator == FilterOperator.BETWEEN:
            return self.value <= actual_value <= (self.value_max or self.value)
        elif self.operator == FilterOperator.IN:
            return actual_value in (self.value if isinstance(self.value, list) else [self.value])

        return False


@dataclass
class ScreenerConfig:
    """Configuration for the asset screener."""
    filters: list[ScreenerFilter] = field(default_factory=list)
    sort_by: str = "market_cap"
    sort_desc: bool = True
    limit: int = 50
    min_market_cap: float = 10_000_000  # $10M minimum


@dataclass
class ScreenerResult:
    """Result for a single screened asset."""
    slug: str
    name: str
    ticker: str
    market_cap: float

    # Metrics that can be filtered/sorted
    metrics: dict = field(default_factory=dict)

    # Pass/fail status for each filter
    filter_results: dict = field(default_factory=dict)

    @property
    def passes_all_filters(self) -> bool:
        return all(self.filter_results.values())

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "ticker": self.ticker,
            "market_cap": self.market_cap,
            "metrics": self.metrics,
            "filter_results": self.filter_results,
        }


class AssetScreener:
    """
    Multi-dimensional asset screener.

    Screens assets based on:
    - Valuation (MVRV, NVT)
    - On-chain activity (DAA, network growth)
    - Social metrics (sentiment, volume)
    - Development activity
    - Whale activity
    - Price performance
    """

    # Available metrics for screening
    AVAILABLE_METRICS = {
        # Valuation
        "mvrv": "MVRV Ratio",
        "nvt": "NVT Ratio",

        # On-chain
        "daily_active_addresses": "Daily Active Addresses",
        "network_growth": "Network Growth (new addresses)",
        "transaction_volume": "Transaction Volume",
        "velocity": "Token Velocity",

        # Social
        "sentiment": "Social Sentiment (-1 to 1)",
        "social_volume": "Social Volume (mentions)",
        "social_dominance": "Social Dominance (%)",

        # Development
        "dev_activity": "Development Activity",
        "contributors": "Active Contributors",

        # Price
        "price_change_24h": "24h Price Change (%)",
        "price_change_7d": "7d Price Change (%)",
        "price_change_30d": "30d Price Change (%)",

        # Whale
        "exchange_inflow": "Exchange Inflow",
        "exchange_outflow": "Exchange Outflow",
        "exchange_net_flow": "Net Exchange Flow",

        # Market
        "market_cap": "Market Cap (USD)",
        "volume_24h": "24h Trading Volume",
    }

    def __init__(self, client: SantimentClient):
        self.client = client

    async def get_asset_metrics(
        self,
        slug: str,
    ) -> dict:
        """
        Fetch all screenable metrics for an asset.

        Returns dict of metric_name -> value
        """
        now = datetime.utcnow()
        from_7d = now - timedelta(days=7)
        from_30d = now - timedelta(days=30)

        # Fetch all data in parallel
        results = await asyncio.gather(
            self.client.get_valuation_metrics(slug, from_7d, now, "1d"),
            self.client.get_network_metrics(slug, from_7d, now, "1d"),
            self.client.get_sentiment(slug, from_7d, now, "1d"),
            self.client.get_dev_activity(slug, from_30d, now, "1d"),
            self.client.get_price(slug, from_30d, now, "1d"),
            self.client.get_exchange_flow(slug, from_7d, now, "1d"),
            return_exceptions=True,
        )

        valuation, network, sentiment, dev, price, exchange = results

        metrics = {}

        # Valuation metrics
        if valuation and not isinstance(valuation, Exception) and valuation:
            latest = valuation[-1]
            metrics["mvrv"] = latest.mvrv_ratio
            metrics["nvt"] = latest.nvt_ratio

        # Network metrics
        if network and not isinstance(network, Exception) and network:
            latest = network[-1]
            metrics["daily_active_addresses"] = latest.daily_active_addresses
            metrics["network_growth"] = latest.network_growth
            metrics["transaction_volume"] = latest.transaction_volume
            metrics["velocity"] = latest.velocity

        # Social metrics
        if sentiment and not isinstance(sentiment, Exception) and sentiment:
            latest = sentiment[-1]
            metrics["sentiment"] = latest.sentiment_weighted
            metrics["social_volume"] = latest.social_volume
            metrics["social_dominance"] = latest.social_dominance

        # Development metrics
        if dev and not isinstance(dev, Exception) and dev:
            # Average over period
            import numpy as np
            metrics["dev_activity"] = np.mean([d.dev_activity for d in dev])
            metrics["contributors"] = max(d.contributors_count for d in dev)

        # Price metrics
        if price and not isinstance(price, Exception) and price:
            current = price[-1].get("closePriceUsd", 0)
            metrics["current_price"] = current

            if len(price) > 1:
                prev_24h = price[-2].get("closePriceUsd", current)
                metrics["price_change_24h"] = ((current - prev_24h) / prev_24h * 100) if prev_24h else 0

            if len(price) > 7:
                prev_7d = price[-8].get("closePriceUsd", current)
                metrics["price_change_7d"] = ((current - prev_7d) / prev_7d * 100) if prev_7d else 0

            if len(price) > 29:
                prev_30d = price[0].get("closePriceUsd", current)
                metrics["price_change_30d"] = ((current - prev_30d) / prev_30d * 100) if prev_30d else 0

            # 24h volume (sum of period)
            metrics["volume_24h"] = sum(p.get("volume", 0) for p in price[-1:])

        # Exchange flow metrics
        if exchange and not isinstance(exchange, Exception) and exchange:
            total_inflow = sum(f.inflow for f in exchange)
            total_outflow = sum(f.outflow for f in exchange)
            metrics["exchange_inflow"] = total_inflow
            metrics["exchange_outflow"] = total_outflow
            metrics["exchange_net_flow"] = total_inflow - total_outflow

        return metrics

    async def screen(
        self,
        config: ScreenerConfig,
        asset_pool: Optional[list[str]] = None,
    ) -> list[ScreenerResult]:
        """
        Screen assets based on configuration.

        Args:
            config: Screening configuration with filters
            asset_pool: Optional list of slugs to screen (fetches all if None)

        Returns:
            List of ScreenerResult for assets passing filters
        """
        # Get asset pool
        if asset_pool is None:
            assets = await self.client.get_all_assets()
            # Filter by market cap
            asset_pool = [
                a.slug for a in assets
                if a.market_cap_usd and a.market_cap_usd >= config.min_market_cap
            ]

        # Sort by market cap initially and limit
        assets = await self.client.get_all_assets()
        asset_map = {a.slug: a for a in assets}

        # Filter to pool and sort by market cap
        pool_assets = [
            asset_map[slug] for slug in asset_pool
            if slug in asset_map and asset_map[slug].market_cap_usd
        ]
        pool_assets.sort(key=lambda a: a.market_cap_usd or 0, reverse=True)
        pool_assets = pool_assets[:min(200, len(pool_assets))]  # Limit for performance

        # Fetch metrics for all assets in parallel (batched)
        results = []
        batch_size = 10

        for i in range(0, len(pool_assets), batch_size):
            batch = pool_assets[i:i+batch_size]
            batch_metrics = await asyncio.gather(
                *[self.get_asset_metrics(a.slug) for a in batch],
                return_exceptions=True,
            )

            for asset, metrics in zip(batch, batch_metrics):
                if isinstance(metrics, Exception):
                    continue

                # Add market cap from asset
                metrics["market_cap"] = asset.market_cap_usd or 0

                # Evaluate filters
                filter_results = {}
                for f in config.filters:
                    metric_value = metrics.get(f.metric)
                    filter_results[f.metric] = f.evaluate(metric_value)

                result = ScreenerResult(
                    slug=asset.slug,
                    name=asset.name,
                    ticker=asset.ticker,
                    market_cap=asset.market_cap_usd or 0,
                    metrics=metrics,
                    filter_results=filter_results,
                )

                # Only include if passes all filters
                if result.passes_all_filters:
                    results.append(result)

        # Sort results
        sort_key = config.sort_by
        results.sort(
            key=lambda r: r.metrics.get(sort_key, 0) or 0,
            reverse=config.sort_desc
        )

        return results[:config.limit]

    async def quick_screen(
        self,
        preset: str,
    ) -> list[ScreenerResult]:
        """
        Run a pre-configured screening preset.

        Available presets:
        - undervalued: MVRV < 1, good dev activity
        - oversold: Large price drop, improving sentiment
        - whale_accumulation: Net outflow from exchanges
        - high_activity: High DAA and network growth
        - momentum: Strong price and sentiment momentum
        """
        presets = {
            "undervalued": ScreenerConfig(
                filters=[
                    ScreenerFilter("mvrv", FilterOperator.LESS_THAN, 1.0),
                    ScreenerFilter("dev_activity", FilterOperator.GREATER_THAN, 20),
                ],
                sort_by="mvrv",
                sort_desc=False,
            ),
            "oversold": ScreenerConfig(
                filters=[
                    ScreenerFilter("price_change_7d", FilterOperator.LESS_THAN, -15),
                    ScreenerFilter("sentiment", FilterOperator.GREATER_THAN, -0.2),
                ],
                sort_by="price_change_7d",
                sort_desc=False,
            ),
            "whale_accumulation": ScreenerConfig(
                filters=[
                    ScreenerFilter("exchange_net_flow", FilterOperator.LESS_THAN, 0),
                ],
                sort_by="exchange_net_flow",
                sort_desc=False,  # Most negative = most outflow
            ),
            "high_activity": ScreenerConfig(
                filters=[
                    ScreenerFilter("daily_active_addresses", FilterOperator.GREATER_THAN, 10000),
                    ScreenerFilter("network_growth", FilterOperator.GREATER_THAN, 1000),
                ],
                sort_by="daily_active_addresses",
                sort_desc=True,
            ),
            "momentum": ScreenerConfig(
                filters=[
                    ScreenerFilter("price_change_7d", FilterOperator.GREATER_THAN, 10),
                    ScreenerFilter("sentiment", FilterOperator.GREATER_THAN, 0.2),
                ],
                sort_by="price_change_7d",
                sort_desc=True,
            ),
        }

        if preset not in presets:
            raise ValueError(f"Unknown preset: {preset}. Available: {list(presets.keys())}")

        return await self.screen(presets[preset])

    @classmethod
    def get_available_metrics(cls) -> dict:
        """Get list of available metrics for screening."""
        return cls.AVAILABLE_METRICS.copy()

    @classmethod
    def get_available_presets(cls) -> dict:
        """Get list of available screening presets."""
        return {
            "undervalued": "MVRV < 1 with good development activity",
            "oversold": "Large price drop with improving sentiment",
            "whale_accumulation": "Net exchange outflows (whales withdrawing)",
            "high_activity": "High daily active addresses and network growth",
            "momentum": "Strong price gains with positive sentiment",
        }
