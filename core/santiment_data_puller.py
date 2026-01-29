"""
Santiment Data Puller — Discovers and bulk-pulls data for the full crypto universe.

Architecture:
  1. DISCOVER: Fetch all ~3500 projects from Santiment, sort by market cap
  2. UNIVERSE PULL: Core metrics (price, mcap, volume) for ALL assets, 7 years
  3. DEEP PULL: Full metric suite for top 200 by market cap, 7 years
  4. REFRESH: Incremental 2-day updates every 4 hours

Designed for Santiment MAX plan:
  - Full historical access (7+ years)
  - Rate limited to 180 requests/minute with dynamic 429 backoff
"""

import asyncio
import time
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from .santiment_client import SantimentClient
from .santiment_cache import SantimentCache
from .cache import CacheManager

logger = logging.getLogger(__name__)

# ================================================================
# METRIC TIERS: Organized by importance for TradFi-style profiles
# ================================================================

# Core metrics — pulled for ALL assets (universe-wide)
CORE_METRICS = [
    "price_usd",
    "volume_usd",
    "marketcap_usd",
]

# Tier 1: Key profile metrics — pulled for top 500 assets
TIER1_METRICS = [
    "price_usd",
    "volume_usd",
    "marketcap_usd",
    "daily_active_addresses",
    "transaction_volume",
    "mvrv_usd",
    "nvt",
    "exchange_balance",
    "dev_activity",
    "network_growth",
]

# Tier 2: Deep analytics — pulled for top 200 assets
TIER2_METRICS = [
    "exchange_inflow",
    "exchange_outflow",
    "circulation",
    "velocity",
    "mean_age",
    "realized_value_usd",
    "mean_realized_price_usd",
    "age_consumed",
    "active_addresses_24h",
    "whale_transaction_count_100k_usd_to_inf",
    "supply_on_exchanges",
    "supply_outside_exchanges",
    "percent_of_total_supply_on_exchanges",
    "sentiment_balance_total",
    "weighted_sentiment_total",
    "social_volume_total",
    "social_dominance_total",
    "dev_activity_contributors_count",
]

# Tier 3: Advanced / niche metrics — pulled for top 100 assets
TIER3_METRICS = [
    "dormant_circulation_90d",
    "dormant_circulation_180d",
    "dormant_circulation_365d",
    "dormant_circulation_2y",
    "dormant_circulation_3y",
    "dormant_circulation_5y",
    "transaction_volume_in_profit",
    "transaction_volume_in_loss",
    "whale_transaction_count_1m_usd_to_inf",
    "active_deposits",
    "active_withdrawals",
    "deposit_transactions",
    "withdrawal_transactions",
    "holders_distribution_combined_balance_0.001_to_0.01",
    "holders_distribution_combined_balance_0.01_to_0.1",
    "holders_distribution_combined_balance_0.1_to_1",
    "holders_distribution_combined_balance_1_to_10",
    "holders_distribution_combined_balance_10_to_100",
    "holders_distribution_combined_balance_100_to_1k",
    "holders_distribution_combined_balance_1k_to_10k",
    "holders_distribution_combined_balance_10k_to_100k",
    "holders_distribution_combined_balance_100k_to_1M",
    "holders_distribution_combined_balance_1M_to_10M",
    "holders_distribution_combined_balance_10M_to_inf",
    "network_profit_loss",
    "gas_used",
    "stock_to_flow",
    "miners_balance",
    "difficulty",
]

ALL_PROFILE_METRICS = TIER1_METRICS + TIER2_METRICS + TIER3_METRICS

# Fallback: hardcoded top tokens in case discovery fails
TOP_TOKENS = [
    "bitcoin", "ethereum", "tether", "xrp", "binance-coin",
    "solana", "usd-coin", "cardano", "dogecoin", "tron",
    "avalanche", "chainlink", "polkadot", "polygon", "shiba-inu",
    "litecoin", "uniswap", "bitcoin-cash", "stellar", "near-protocol",
    "internet-computer", "cosmos", "filecoin",
    "aave", "maker", "the-graph", "render-token", "injective",
    "fantom", "algorand", "hedera-hashgraph",
    "multiversx-egld", "flow", "axie-infinity", "decentraland", "the-sandbox",
    "lido-dao", "rocket-pool", "compound", "sushiswap", "curve",
    "yearn-finance", "1inch", "ethereum-name-service", "convex-finance", "gmx",
    "pepe", "bonk", "sui", "aptos", "sei-network",
    "celestia", "stacks", "mantle", "immutable-x",
]

# History depth
MAX_YEARS = 7


class SantimentDataPuller:
    """Orchestrates discovery and bulk data pulling for the full crypto universe."""

    def __init__(self, client: SantimentClient, cache: SantimentCache):
        self._client = client
        self._cache = cache
        self._results = {
            "discovery": {},
            "pull_stats": {},
        }
        self._valid_slugs: set[str] = set()
        self._universe_slugs: list[str] = []  # All slugs sorted by market cap

    @property
    def universe_size(self) -> int:
        return len(self._universe_slugs)

    # ================================================================
    # DISCOVERY — Fetch all projects, build the universe
    # ================================================================

    async def discover_universe(self) -> list[str]:
        """
        Discover ALL projects from Santiment, sort by market cap.
        Returns list of slugs ordered by market cap descending.
        """
        logger.info("UNIVERSE DISCOVERY: Fetching all projects from Santiment...")
        start = time.time()

        try:
            projects = await self._client.get_all_projects()
            stored = self._cache.store_projects(projects)
            self._valid_slugs = {p["slug"] for p in projects if p.get("slug")}

            # Sort by market cap, filter out those without a slug
            with_mcap = [p for p in projects if p.get("slug") and p.get("marketcapUsd")]
            with_mcap.sort(key=lambda x: float(x.get("marketcapUsd") or 0), reverse=True)

            # Also include projects without mcap at the end
            without_mcap = [p for p in projects if p.get("slug") and not p.get("marketcapUsd")]

            self._universe_slugs = [p["slug"] for p in with_mcap] + [p["slug"] for p in without_mcap]

            elapsed = time.time() - start
            logger.info(
                f"UNIVERSE DISCOVERY complete in {elapsed:.1f}s: "
                f"{len(projects)} total projects, {len(with_mcap)} with market cap, "
                f"{stored} stored. Universe: {len(self._universe_slugs)} slugs"
            )

            self._results["discovery"] = {
                "total_projects": len(projects),
                "with_marketcap": len(with_mcap),
                "without_marketcap": len(without_mcap),
                "universe_size": len(self._universe_slugs),
                "elapsed_seconds": round(elapsed, 1),
                "top_10": self._universe_slugs[:10],
            }

            return self._universe_slugs

        except Exception as e:
            logger.error(f"UNIVERSE DISCOVERY failed, falling back to TOP_TOKENS: {e}")
            self._valid_slugs = set(TOP_TOKENS)
            self._universe_slugs = list(TOP_TOKENS)
            self._results["discovery"] = {"error": str(e), "fallback": True}
            return self._universe_slugs

    async def run_lightweight_discovery(self) -> dict:
        """Minimal discovery — just validate slugs by fetching projects."""
        return {"slugs": await self.discover_universe()}

    # ================================================================
    # PULL HELPERS
    # ================================================================

    async def pull_metric_for_tokens(
        self,
        metric: str,
        slugs: list[str],
        years_back: int = 3,
        interval: str = "1d",
    ) -> dict:
        """Pull one metric for all target tokens."""
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=years_back * 365)).strftime("%Y-%m-%dT00:00:00Z")

        stats = {"metric": metric, "success": 0, "failed": 0, "skipped": 0, "total_points": 0, "errors": []}

        for i, slug in enumerate(slugs):
            if self._cache.was_pulled(metric, slug, from_date, to_date, interval):
                stats["skipped"] += 1
                stats["success"] += 1
                continue

            try:
                data = await self._client.get_metric_timeseries(
                    metric, slug, from_date, to_date, interval
                )
                points = self._cache.store_timeseries(metric, slug, data, interval)
                self._cache.log_pull(metric, slug, from_date, to_date, points, interval)
                stats["success"] += 1
                stats["total_points"] += points
                if (i + 1) % 50 == 0:
                    logger.info(f"  {metric} [{i+1}/{len(slugs)}]: {stats['total_points']} pts, {stats['skipped']} skipped")
            except Exception as e:
                stats["failed"] += 1
                error_str = str(e)[:200]
                if len(stats["errors"]) < 5:
                    stats["errors"].append({"slug": slug, "error": error_str})
                self._cache.log_pull(metric, slug, from_date, to_date, 0, interval, "error", error_str)

        return stats

    async def pull_ohlcv_for_tokens(
        self,
        slugs: list[str],
        years_back: int = 5,
    ) -> dict:
        """Pull OHLCV price data for all target tokens."""
        logger.info(f"OHLCV PULL: {len(slugs)} tokens, {years_back} years...")
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=years_back * 365)).strftime("%Y-%m-%dT00:00:00Z")

        stats = {"success": 0, "failed": 0, "skipped": 0, "total_points": 0, "errors": []}

        for i, slug in enumerate(slugs):
            if self._cache.was_pulled("ohlcv", slug, from_date, to_date):
                stats["skipped"] += 1
                stats["success"] += 1
                continue

            try:
                data = await self._client.get_ohlcv(slug, from_date, to_date, "1d")
                points = self._cache.store_ohlcv(slug, data)
                self._cache.log_pull("ohlcv", slug, from_date, to_date, points)
                stats["success"] += 1
                stats["total_points"] += points
                if (i + 1) % 50 == 0:
                    logger.info(f"  OHLCV [{i+1}/{len(slugs)}]: {stats['total_points']} pts")
            except Exception as e:
                stats["failed"] += 1
                if len(stats["errors"]) < 5:
                    stats["errors"].append({"slug": slug, "error": str(e)[:200]})
                self._cache.log_pull("ohlcv", slug, from_date, to_date, 0, status="error", error_message=str(e)[:200])

        return stats

    # ================================================================
    # PHASE 1: LIGHTWEIGHT PULL — Get core data fast for initial display
    # ================================================================

    async def run_lightweight_pull(
        self,
        slugs: Optional[list[str]] = None,
        years_back: int = 1,
    ) -> dict:
        """
        Quick pull of core data for fast startup.
        Pulls Tier 1 metrics for top 10 tokens, 1 year.
        """
        target_slugs = (slugs or self._universe_slugs or TOP_TOKENS)[:10]

        if self._valid_slugs:
            target_slugs = [s for s in target_slugs if s in self._valid_slugs]

        logger.info("=" * 60)
        logger.info(f"LIGHTWEIGHT PULL: {len(target_slugs)} tokens, Tier 1, {years_back}y")
        logger.info("=" * 60)
        start = time.time()

        stats = {"ohlcv": {"success": 0, "failed": 0}, "metrics": {}, "total_points": 0}

        # Pull OHLCV
        for slug in target_slugs:
            try:
                to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
                from_date = (datetime.now(timezone.utc) - timedelta(days=years_back * 365)).strftime("%Y-%m-%dT00:00:00Z")

                if not self._cache.was_pulled("ohlcv", slug, from_date, to_date):
                    data = await self._client.get_ohlcv(slug, from_date, to_date, "1d")
                    points = self._cache.store_ohlcv(slug, data)
                    self._cache.log_pull("ohlcv", slug, from_date, to_date, points)
                    stats["total_points"] += points
                stats["ohlcv"]["success"] += 1
            except Exception as e:
                stats["ohlcv"]["failed"] += 1
                logger.warning(f"  OHLCV {slug}: FAILED - {e}")

        # Pull Tier 1 metrics
        for metric in TIER1_METRICS:
            metric_stats = {"success": 0, "failed": 0, "points": 0}
            for slug in target_slugs:
                try:
                    to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
                    from_date = (datetime.now(timezone.utc) - timedelta(days=years_back * 365)).strftime("%Y-%m-%dT00:00:00Z")

                    if not self._cache.was_pulled(metric, slug, from_date, to_date):
                        data = await self._client.get_metric_timeseries(
                            metric, slug, from_date, to_date, "1d"
                        )
                        points = self._cache.store_timeseries(metric, slug, data)
                        self._cache.log_pull(metric, slug, from_date, to_date, points)
                        metric_stats["points"] += points
                        stats["total_points"] += points
                    metric_stats["success"] += 1
                except Exception as e:
                    metric_stats["failed"] += 1
                    logger.warning(f"  {metric}/{slug}: FAILED - {e}")

            stats["metrics"][metric] = metric_stats
            logger.info(f"  {metric}: {metric_stats['success']} ok, {metric_stats['failed']} fail, {metric_stats['points']} pts")

        # Pull fundamentals
        for slug in target_slugs:
            try:
                data = await self._client.get_project_fundamentals(slug)
                if data:
                    self._cache.store_projects([data])
            except Exception as e:
                logger.warning(f"  Fundamentals {slug}: FAILED - {e}")

        elapsed = time.time() - start
        stats["elapsed_seconds"] = round(elapsed, 1)
        stats["cache_stats"] = self._cache.get_pull_stats()
        logger.info(f"LIGHTWEIGHT PULL COMPLETE: {stats['total_points']} points in {elapsed:.1f}s")
        return stats

    # ================================================================
    # PHASE 2: UNIVERSE PULL — Core metrics for ALL assets
    # ================================================================

    async def run_universe_pull(self) -> dict:
        """
        Pull core metrics (price, mcap, volume) for the entire universe.
        This gives us basic data for every single token on Santiment.

        Strategy:
          - All universe slugs, 7 years of history
          - Only CORE_METRICS (3 metrics) to keep API usage manageable
          - ~3500 slugs × 3 metrics = ~10,500 API calls
        """
        universe = self._universe_slugs or TOP_TOKENS
        years = MAX_YEARS

        logger.info("=" * 60)
        logger.info(f"UNIVERSE PULL: {len(universe)} tokens × {len(CORE_METRICS)} core metrics × {years}y")
        logger.info(f"  Estimated API calls: ~{len(universe) * len(CORE_METRICS)}")
        logger.info("=" * 60)
        start = time.time()

        all_stats = {"metrics": {}, "total_points": 0, "total_success": 0, "total_failed": 0}

        for mi, metric in enumerate(CORE_METRICS):
            logger.info(f"\nUNIVERSE: Metric [{mi+1}/{len(CORE_METRICS)}]: {metric}")
            try:
                metric_stats = await self.pull_metric_for_tokens(
                    metric, universe, years_back=years
                )
                all_stats["metrics"][metric] = metric_stats
                all_stats["total_points"] += metric_stats["total_points"]
                all_stats["total_success"] += metric_stats["success"]
                all_stats["total_failed"] += metric_stats["failed"]
                logger.info(
                    f"  {metric}: {metric_stats['success']} ok, "
                    f"{metric_stats['failed']} fail, "
                    f"{metric_stats['skipped']} skipped, "
                    f"{metric_stats['total_points']} pts"
                )
            except Exception as e:
                logger.error(f"  Universe metric {metric} failed: {e}")
                all_stats["metrics"][metric] = {"error": str(e)}

        elapsed = time.time() - start
        all_stats["elapsed_seconds"] = round(elapsed, 1)
        all_stats["elapsed_minutes"] = round(elapsed / 60, 1)
        all_stats["cache_stats"] = self._cache.get_pull_stats()
        logger.info(f"\nUNIVERSE PULL COMPLETE: {all_stats['total_points']} points in {elapsed/60:.1f}min")
        return all_stats

    # ================================================================
    # PHASE 3: DEEP PULL — Full metrics for top N tokens
    # ================================================================

    async def run_deep_pull(
        self,
        top_n: int = 200,
        years_back: int = MAX_YEARS,
        tiers: list[int] = [1, 2],
    ) -> dict:
        """
        Deep pull of full metric suite for top tokens by market cap.

        Args:
            top_n: Number of top tokens to pull deep data for
            years_back: Years of history
            tiers: Which metric tiers to include
        """
        universe = self._universe_slugs or TOP_TOKENS
        target_slugs = universe[:top_n]

        target_metrics = []
        if 1 in tiers:
            target_metrics.extend(TIER1_METRICS)
        if 2 in tiers:
            target_metrics.extend(TIER2_METRICS)
        if 3 in tiers:
            target_metrics.extend(TIER3_METRICS)

        # Deduplicate (core metrics already in tier 1)
        seen = set()
        deduped = []
        for m in target_metrics:
            if m not in seen:
                seen.add(m)
                deduped.append(m)
        target_metrics = deduped

        # Filter out core metrics already pulled in universe phase
        non_core = [m for m in target_metrics if m not in CORE_METRICS]

        total_combos = len(target_slugs) * len(non_core)
        logger.info("=" * 60)
        logger.info(f"DEEP PULL: {len(target_slugs)} tokens × {len(non_core)} metrics × {years_back}y")
        logger.info(f"  (Skipping {len(CORE_METRICS)} core metrics already pulled in universe phase)")
        logger.info(f"  Estimated API calls: ~{total_combos}")
        logger.info("=" * 60)
        start = time.time()

        all_stats = {"metrics": {}, "ohlcv": {}, "total_points": 0, "total_success": 0, "total_failed": 0}

        # Pull OHLCV
        logger.info("\n--- OHLCV Price Data ---")
        try:
            all_stats["ohlcv"] = await self.pull_ohlcv_for_tokens(target_slugs, years_back)
            all_stats["total_points"] += all_stats["ohlcv"].get("total_points", 0)
        except Exception as e:
            logger.error(f"OHLCV phase failed: {e}")
            all_stats["ohlcv"] = {"error": str(e)}

        # Pull each metric
        logger.info("\n--- Metric Timeseries ---")
        for mi, metric in enumerate(non_core):
            logger.info(f"\nDEEP Metric [{mi+1}/{len(non_core)}]: {metric}")
            try:
                metric_stats = await self.pull_metric_for_tokens(
                    metric, target_slugs, years_back
                )
                all_stats["metrics"][metric] = metric_stats
                all_stats["total_points"] += metric_stats["total_points"]
                all_stats["total_success"] += metric_stats["success"]
                all_stats["total_failed"] += metric_stats["failed"]
                logger.info(
                    f"  {metric}: {metric_stats['success']} ok, "
                    f"{metric_stats['failed']} fail, "
                    f"{metric_stats['total_points']} pts"
                )
            except Exception as e:
                logger.error(f"  Deep metric {metric} failed: {e}")
                all_stats["metrics"][metric] = {"error": str(e)}

        elapsed = time.time() - start
        all_stats["elapsed_seconds"] = round(elapsed, 1)
        all_stats["elapsed_minutes"] = round(elapsed / 60, 1)
        all_stats["cache_stats"] = self._cache.get_pull_stats()
        logger.info(f"\nDEEP PULL COMPLETE: {all_stats['total_points']} points in {elapsed/60:.1f}min")
        return all_stats

    # ================================================================
    # LEGACY: run_bulk_pull for backward compat
    # ================================================================

    async def run_bulk_pull(
        self,
        slugs: Optional[list[str]] = None,
        metrics: Optional[list[str]] = None,
        years_back: int = 3,
        tiers: list[int] = [1, 2],
    ) -> dict:
        """Run bulk data pull (legacy interface, now wraps deep pull)."""
        raw_slugs = slugs or self._universe_slugs or TOP_TOKENS
        target_metrics = metrics or []
        if not target_metrics:
            if 1 in tiers:
                target_metrics.extend(TIER1_METRICS)
            if 2 in tiers:
                target_metrics.extend(TIER2_METRICS)
            if 3 in tiers:
                target_metrics.extend(TIER3_METRICS)

        if self._valid_slugs:
            target_slugs = [s for s in raw_slugs if s in self._valid_slugs]
        else:
            target_slugs = raw_slugs

        logger.info("=" * 60)
        logger.info(f"BULK PULL: {len(target_slugs)} tokens × {len(target_metrics)} metrics × {years_back}y")
        logger.info("=" * 60)
        start = time.time()

        all_stats = {"metrics": {}, "ohlcv": {}, "total_points": 0}

        # Pull OHLCV
        try:
            all_stats["ohlcv"] = await self.pull_ohlcv_for_tokens(target_slugs, years_back)
        except Exception as e:
            all_stats["ohlcv"] = {"error": str(e)}

        # Pull each metric
        for mi, metric in enumerate(target_metrics):
            logger.info(f"\nMetric [{mi+1}/{len(target_metrics)}]: {metric}")
            try:
                metric_stats = await self.pull_metric_for_tokens(
                    metric, target_slugs, years_back
                )
                all_stats["metrics"][metric] = metric_stats
                all_stats["total_points"] += metric_stats.get("total_points", 0)
            except Exception as e:
                all_stats["metrics"][metric] = {"error": str(e)}

        elapsed = time.time() - start
        all_stats["elapsed_seconds"] = round(elapsed, 1)
        all_stats["cache_stats"] = self._cache.get_pull_stats()
        return all_stats

    # ================================================================
    # DAILY REFRESH: Incremental update
    # ================================================================

    async def daily_refresh(
        self,
        slugs: Optional[list[str]] = None,
        metrics: Optional[list[str]] = None,
    ) -> dict:
        """
        Incremental refresh — only pull last 2 days of data.
        Uses batch queries for efficiency.
        """
        # Refresh universe (top 500 + core metrics, top 200 + deep metrics)
        universe = slugs or self._universe_slugs or TOP_TOKENS
        core_slugs = universe[:500]
        deep_slugs = universe[:200]
        core_metrics_list = metrics or CORE_METRICS
        deep_metrics_list = [m for m in (TIER1_METRICS + TIER2_METRICS) if m not in CORE_METRICS]

        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")

        logger.info(f"DAILY REFRESH: core={len(core_slugs)} slugs × {len(core_metrics_list)} metrics, "
                     f"deep={len(deep_slugs)} slugs × {len(deep_metrics_list)} metrics")
        start = time.time()
        stats = {"success": 0, "failed": 0, "total_points": 0}

        # Refresh core metrics for top 500
        for slug in core_slugs:
            for i in range(0, len(core_metrics_list), 3):
                batch = core_metrics_list[i:i+3]
                try:
                    data = await self._client.get_multiple_metrics_for_slug(
                        batch, slug, from_date, to_date, "1d"
                    )
                    for metric, points in data.items():
                        stored = self._cache.store_timeseries(metric, slug, points)
                        stats["total_points"] += stored
                    stats["success"] += 1
                except Exception as e:
                    stats["failed"] += 1

        # Refresh deep metrics for top 200
        for slug in deep_slugs:
            for i in range(0, len(deep_metrics_list), 5):
                batch = deep_metrics_list[i:i+5]
                try:
                    data = await self._client.get_multiple_metrics_for_slug(
                        batch, slug, from_date, to_date, "1d"
                    )
                    for metric, points in data.items():
                        stored = self._cache.store_timeseries(metric, slug, points)
                        stats["total_points"] += stored
                    stats["success"] += 1
                except Exception as e:
                    stats["failed"] += 1

            # OHLCV separately
            try:
                ohlcv = await self._client.get_ohlcv(slug, from_date, to_date, "1d")
                self._cache.store_ohlcv(slug, ohlcv)
            except Exception:
                pass

        elapsed = time.time() - start
        stats["elapsed_seconds"] = round(elapsed, 1)
        logger.info(f"DAILY REFRESH COMPLETE: {stats['total_points']} points in {elapsed:.1f}s")
        return stats

    # ================================================================
    # REPORT
    # ================================================================

    def get_full_report(self) -> dict:
        return {
            **self._results,
            "universe_size": len(self._universe_slugs),
            "client_stats": self._client.stats,
            "cache_stats": self._cache.get_pull_stats(),
        }
