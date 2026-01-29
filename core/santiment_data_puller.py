"""
Santiment Data Puller — Discovers, stress-tests, and bulk-pulls data.

Three modes:
  1. DISCOVER: Map the entire API surface (metrics, slugs, metadata)
  2. STRESS TEST: Measure rate limits, response times, data volumes
  3. BULK PULL: Systematically pull all historical data for target tokens

Designed for Santiment Pro plan:
  - 600 requests/minute
  - 30,000 requests/hour
  - 600,000 requests/month
  - Full historical access (7+ years)
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

# Tier 1: Core profile metrics (must-have for any token page)
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

# Tier 2: Deep analytics (valuation, flows, distribution)
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

# Tier 3: Advanced / niche metrics
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

# Top tokens by market cap — our target universe
# NOTE: Slugs must match Santiment's project slugs exactly.
# Discovery phase validates these against the API and skips invalid ones.
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


class SantimentDataPuller:
    """Orchestrates discovery, stress testing, and bulk data pulling."""

    def __init__(self, client: SantimentClient, cache: SantimentCache):
        self._client = client
        self._cache = cache
        self._results = {
            "discovery": {},
            "stress_test": {},
            "pull_stats": {},
        }
        self._valid_slugs: set[str] = set()  # Populated during discovery

    # ================================================================
    # PHASE 1: DISCOVERY — Map the API surface
    # ================================================================

    async def discover_all_metrics(self) -> list[str]:
        """Pull the complete list of available metrics."""
        logger.info("DISCOVERY: Fetching all available metrics...")
        metrics = await self._client.get_all_available_metrics()
        logger.info(f"  Found {len(metrics)} total metrics")
        self._results["discovery"]["total_metrics"] = len(metrics)
        self._results["discovery"]["all_metrics"] = metrics
        return metrics

    async def discover_all_projects(self) -> list[dict]:
        """Pull all projects and store in cache. Populates _valid_slugs."""
        logger.info("DISCOVERY: Fetching all projects...")
        projects = await self._client.get_all_projects()
        stored = self._cache.store_projects(projects)
        logger.info(f"  Found {len(projects)} projects, stored {stored}")
        self._results["discovery"]["total_projects"] = len(projects)

        # Build set of all valid slugs
        self._valid_slugs = {p["slug"] for p in projects if p.get("slug")}
        logger.info(f"  Valid slugs in Santiment: {len(self._valid_slugs)}")

        # Validate our TOP_TOKENS list against actual slugs
        valid_top = [s for s in TOP_TOKENS if s in self._valid_slugs]
        invalid_top = [s for s in TOP_TOKENS if s not in self._valid_slugs]
        if invalid_top:
            logger.warning(f"  Invalid slugs in TOP_TOKENS (will skip): {invalid_top}")
        self._results["discovery"]["valid_top_tokens"] = valid_top
        self._results["discovery"]["invalid_top_tokens"] = invalid_top

        # Sort by market cap to find the top ones
        with_mcap = [p for p in projects if p.get("marketcapUsd")]
        with_mcap.sort(key=lambda x: float(x["marketcapUsd"] or 0), reverse=True)
        top_slugs = [p["slug"] for p in with_mcap[:100]]
        self._results["discovery"]["top_100_slugs"] = top_slugs
        return projects

    async def discover_metric_metadata(self, metrics: list[str]) -> list[dict]:
        """Pull metadata for each metric (min interval, data type, accessibility)."""
        logger.info(f"DISCOVERY: Fetching metadata for {len(metrics)} metrics...")
        results = []
        batch_size = 5  # parallel metadata requests
        for i in range(0, len(metrics), batch_size):
            batch = metrics[i:i+batch_size]
            tasks = [self._client.get_metric_metadata(m) for m in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for metric, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.warning(f"  Metadata error for {metric}: {result}")
                    results.append({"metric": metric, "error": str(result)})
                else:
                    result["metric"] = metric
                    results.append(result)
            if i % 50 == 0 and i > 0:
                logger.info(f"  ...metadata progress: {i}/{len(metrics)}")

        # Store in cache
        catalog_entries = []
        for r in results:
            if "error" not in r:
                catalog_entries.append({
                    "metric": r["metric"],
                    "min_interval": r.get("minInterval"),
                    "default_aggregation": r.get("defaultAggregation"),
                    "data_type": r.get("dataType"),
                    "is_accessible": r.get("isAccessible"),
                    "is_restricted": r.get("isRestricted"),
                    "available_slugs_count": 0,
                })
        self._cache.store_metrics_catalog(catalog_entries)

        accessible = sum(1 for r in results if r.get("isAccessible"))
        restricted = sum(1 for r in results if r.get("isRestricted"))
        logger.info(f"  Accessible: {accessible}, Restricted: {restricted}")
        self._results["discovery"]["accessible_metrics"] = accessible
        self._results["discovery"]["restricted_metrics"] = restricted
        return results

    async def discover_slugs_per_metric(self, metrics: list[str]) -> dict[str, int]:
        """For key metrics, discover how many slugs have data."""
        logger.info(f"DISCOVERY: Checking slug availability for {len(metrics)} key metrics...")
        slug_counts = {}
        for i, metric in enumerate(metrics):
            try:
                slugs = await self._client.get_available_slugs_for_metric(metric)
                slug_counts[metric] = len(slugs)
                self._cache.store_metric_slugs(metric, slugs)
                # Update catalog
                self._cache._conn.execute(
                    "UPDATE metrics_catalog SET available_slugs_count = ? WHERE metric = ?",
                    (len(slugs), metric),
                )
                self._cache._conn.commit()
                logger.info(f"  {metric}: {len(slugs)} slugs")
            except Exception as e:
                logger.warning(f"  {metric}: error - {e}")
                slug_counts[metric] = -1
        self._results["discovery"]["slug_counts"] = slug_counts
        return slug_counts

    async def run_full_discovery(self) -> dict:
        """Run complete API discovery."""
        logger.info("=" * 60)
        logger.info("STARTING FULL API DISCOVERY")
        logger.info("=" * 60)
        start = time.time()

        # Step 1: Get all metrics
        all_metrics = await self.discover_all_metrics()

        # Step 2: Get all projects
        await self.discover_all_projects()

        # Step 3: Get metadata for our target metrics
        target_metrics = [m for m in ALL_PROFILE_METRICS if m in all_metrics]
        missing = [m for m in ALL_PROFILE_METRICS if m not in all_metrics]
        if missing:
            logger.warning(f"  Metrics NOT available: {missing}")
        self._results["discovery"]["target_metrics_available"] = len(target_metrics)
        self._results["discovery"]["target_metrics_missing"] = missing

        await self.discover_metric_metadata(target_metrics)

        # Step 4: Get slug availability for tier 1 metrics
        tier1_available = [m for m in TIER1_METRICS if m in all_metrics]
        await self.discover_slugs_per_metric(tier1_available)

        elapsed = time.time() - start
        self._results["discovery"]["elapsed_seconds"] = round(elapsed, 1)
        self._results["discovery"]["api_calls_used"] = self._client.stats["total_requests"]
        logger.info(f"DISCOVERY COMPLETE in {elapsed:.1f}s using {self._client.stats['total_requests']} API calls")
        return self._results["discovery"]

    # ================================================================
    # PHASE 2: STRESS TEST — Measure limits and throughput
    # ================================================================

    async def stress_test_single_metric(self, metric: str, slug: str = "bitcoin") -> dict:
        """Test a single metric: measure response time and data volume."""
        # Pull 1 year of daily data
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00Z")

        start = time.time()
        try:
            data = await self._client.get_metric_timeseries(
                metric, slug, from_date, to_date, "1d"
            )
            elapsed = time.time() - start
            return {
                "metric": metric,
                "slug": slug,
                "data_points": len(data),
                "response_time_ms": round(elapsed * 1000),
                "status": "success",
                "sample_first": data[0] if data else None,
                "sample_last": data[-1] if data else None,
            }
        except Exception as e:
            elapsed = time.time() - start
            return {
                "metric": metric,
                "slug": slug,
                "data_points": 0,
                "response_time_ms": round(elapsed * 1000),
                "status": "error",
                "error": str(e),
            }

    async def stress_test_batch_query(self, slug: str = "bitcoin") -> dict:
        """Test batching multiple metrics in one request."""
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00Z")

        # Try batching 5 metrics at once
        batch_metrics = TIER1_METRICS[:5]
        start = time.time()
        try:
            data = await self._client.get_multiple_metrics_for_slug(
                batch_metrics, slug, from_date, to_date, "1d"
            )
            elapsed = time.time() - start
            total_points = sum(len(v) for v in data.values())
            return {
                "metrics_batched": len(batch_metrics),
                "total_data_points": total_points,
                "response_time_ms": round(elapsed * 1000),
                "points_per_metric": {k: len(v) for k, v in data.items()},
                "status": "success",
            }
        except Exception as e:
            elapsed = time.time() - start
            return {
                "metrics_batched": len(batch_metrics),
                "response_time_ms": round(elapsed * 1000),
                "status": "error",
                "error": str(e),
            }

    async def stress_test_max_history(self, metric: str = "price_usd", slug: str = "bitcoin") -> dict:
        """Test maximum historical depth available."""
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        # Try 10 years back
        from_date = (datetime.now(timezone.utc) - timedelta(days=3650)).strftime("%Y-%m-%dT00:00:00Z")

        start = time.time()
        try:
            data = await self._client.get_metric_timeseries(
                metric, slug, from_date, to_date, "1d"
            )
            elapsed = time.time() - start
            years = len(data) / 365.0 if data else 0
            return {
                "metric": metric,
                "slug": slug,
                "data_points": len(data),
                "years_of_data": round(years, 1),
                "earliest_date": data[0]["datetime"] if data else None,
                "latest_date": data[-1]["datetime"] if data else None,
                "response_time_ms": round(elapsed * 1000),
                "status": "success",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def stress_test_rate_burst(self, count: int = 20) -> dict:
        """Fire N requests in rapid succession to measure actual rate limit behavior."""
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")

        slugs = TOP_TOKENS[:count]
        start = time.time()

        tasks = [
            self._client.get_metric_timeseries("price_usd", slug, from_date, to_date, "1d")
            for slug in slugs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - start

        successes = sum(1 for r in results if not isinstance(r, Exception))
        errors = sum(1 for r in results if isinstance(r, Exception))
        total_points = sum(len(r) for r in results if not isinstance(r, Exception) and r)

        return {
            "burst_count": count,
            "successes": successes,
            "errors": errors,
            "total_data_points": total_points,
            "elapsed_seconds": round(elapsed, 2),
            "requests_per_second": round(count / elapsed, 1) if elapsed > 0 else 0,
            "error_details": [str(r) for r in results if isinstance(r, Exception)][:5],
        }

    async def stress_test_ohlcv(self, slug: str = "bitcoin") -> dict:
        """Test OHLCV data pull (different query structure)."""
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=3650)).strftime("%Y-%m-%dT00:00:00Z")

        start = time.time()
        try:
            data = await self._client.get_ohlcv(slug, from_date, to_date, "1d")
            elapsed = time.time() - start
            return {
                "slug": slug,
                "data_points": len(data),
                "years": round(len(data) / 365.0, 1) if data else 0,
                "earliest": data[0]["datetime"] if data else None,
                "response_time_ms": round(elapsed * 1000),
                "status": "success",
                "sample": data[0] if data else None,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def run_stress_test(self) -> dict:
        """Run the full stress test suite."""
        logger.info("=" * 60)
        logger.info("STARTING API STRESS TEST")
        logger.info("=" * 60)
        start = time.time()
        results = {}

        # Test 1: Individual metric response times
        logger.info("TEST 1: Individual metric response times...")
        metric_tests = []
        for metric in TIER1_METRICS:
            result = await self.stress_test_single_metric(metric)
            metric_tests.append(result)
            status = "OK" if result["status"] == "success" else "FAIL"
            logger.info(f"  {metric}: {result['data_points']} pts, {result['response_time_ms']}ms [{status}]")
        results["individual_metrics"] = metric_tests

        # Test 2: Batch query
        logger.info("TEST 2: Batch query (5 metrics in 1 request)...")
        results["batch_query"] = await self.stress_test_batch_query()
        logger.info(f"  Result: {results['batch_query']}")

        # Test 3: Maximum historical depth
        logger.info("TEST 3: Maximum historical depth (10 years)...")
        results["max_history"] = await self.stress_test_max_history()
        logger.info(f"  Result: {results['max_history'].get('years_of_data', 'N/A')} years, "
                    f"{results['max_history'].get('data_points', 0)} points")

        # Test 4: Rate burst
        logger.info("TEST 4: Rate burst (20 concurrent requests)...")
        results["rate_burst"] = await self.stress_test_rate_burst(20)
        logger.info(f"  Result: {results['rate_burst']['successes']}/{results['rate_burst']['burst_count']} success, "
                    f"{results['rate_burst']['requests_per_second']} req/s")

        # Test 5: OHLCV
        logger.info("TEST 5: OHLCV data (10 years)...")
        results["ohlcv"] = await self.stress_test_ohlcv()
        logger.info(f"  Result: {results['ohlcv']}")

        # Test 6: Multi-slug test for a single metric
        logger.info("TEST 6: Multi-slug coverage (50 tokens, price_usd)...")
        multi_slug_results = []
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
        for slug in TOP_TOKENS[:50]:
            try:
                data = await self._client.get_metric_timeseries("price_usd", slug, from_date, to_date, "1d")
                multi_slug_results.append({"slug": slug, "points": len(data), "status": "ok"})
            except Exception as e:
                multi_slug_results.append({"slug": slug, "points": 0, "status": "error", "error": str(e)})
        success_count = sum(1 for r in multi_slug_results if r["status"] == "ok")
        results["multi_slug"] = {
            "tested": len(multi_slug_results),
            "successes": success_count,
            "failures": len(multi_slug_results) - success_count,
            "failed_slugs": [r["slug"] for r in multi_slug_results if r["status"] != "ok"],
            "details": multi_slug_results,
        }
        logger.info(f"  Result: {success_count}/{len(multi_slug_results)} slugs returned data")

        elapsed = time.time() - start
        results["total_elapsed_seconds"] = round(elapsed, 1)
        results["total_api_calls"] = self._client.stats["total_requests"]
        results["total_data_points_fetched"] = self._client.stats["total_data_points"]

        self._results["stress_test"] = results
        logger.info(f"STRESS TEST COMPLETE in {elapsed:.1f}s")
        logger.info(f"  Total API calls: {self._client.stats['total_requests']}")
        logger.info(f"  Total data points: {self._client.stats['total_data_points']}")
        return results

    # ================================================================
    # PHASE 3: BULK PULL — Pull all data and cache it
    # ================================================================

    async def pull_ohlcv_for_tokens(
        self,
        slugs: list[str],
        years_back: int = 5,
    ) -> dict:
        """Pull OHLCV price data for all target tokens."""
        logger.info(f"BULK PULL: OHLCV for {len(slugs)} tokens, {years_back} years...")
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=years_back * 365)).strftime("%Y-%m-%dT00:00:00Z")

        stats = {"success": 0, "failed": 0, "total_points": 0, "errors": []}

        for i, slug in enumerate(slugs):
            if self._cache.was_pulled("ohlcv", slug, from_date, to_date):
                logger.info(f"  [{i+1}/{len(slugs)}] {slug}: already cached, skipping")
                stats["success"] += 1
                continue

            try:
                data = await self._client.get_ohlcv(slug, from_date, to_date, "1d")
                points = self._cache.store_ohlcv(slug, data)
                self._cache.log_pull("ohlcv", slug, from_date, to_date, points)
                stats["success"] += 1
                stats["total_points"] += points
                logger.info(f"  [{i+1}/{len(slugs)}] {slug}: {points} OHLCV points stored")
            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append({"slug": slug, "error": str(e)})
                self._cache.log_pull("ohlcv", slug, from_date, to_date, 0, status="error", error_message=str(e))
                logger.warning(f"  [{i+1}/{len(slugs)}] {slug}: FAILED - {e}")

        return stats

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

        stats = {"metric": metric, "success": 0, "failed": 0, "total_points": 0, "errors": []}

        for i, slug in enumerate(slugs):
            if self._cache.was_pulled(metric, slug, from_date, to_date, interval):
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
                if (i + 1) % 10 == 0:
                    logger.info(f"  {metric} [{i+1}/{len(slugs)}]: {stats['total_points']} points so far")
            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append({"slug": slug, "error": str(e)})
                self._cache.log_pull(metric, slug, from_date, to_date, 0, interval, "error", str(e))

        return stats

    async def pull_fundamentals_for_tokens(self, slugs: list[str]) -> dict:
        """Pull project fundamentals for all tokens."""
        logger.info(f"BULK PULL: Fundamentals for {len(slugs)} tokens...")
        stats = {"success": 0, "failed": 0, "errors": []}

        for i, slug in enumerate(slugs):
            try:
                data = await self._client.get_project_fundamentals(slug)
                if data:
                    self._cache.store_projects([data])
                    stats["success"] += 1
            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append({"slug": slug, "error": str(e)})

            if (i + 1) % 20 == 0:
                logger.info(f"  Fundamentals [{i+1}/{len(slugs)}]")

        return stats

    async def run_bulk_pull(
        self,
        slugs: Optional[list[str]] = None,
        metrics: Optional[list[str]] = None,
        years_back: int = 3,
        tiers: list[int] = [1, 2],
    ) -> dict:
        """
        Run the full bulk data pull.

        Args:
            slugs: Token slugs to pull (default: TOP_TOKENS)
            metrics: Specific metrics to pull (default: based on tiers)
            years_back: Years of history to pull
            tiers: Which metric tiers to include [1], [1,2], or [1,2,3]
        """
        raw_slugs = slugs or TOP_TOKENS
        target_metrics = metrics or []
        if not target_metrics:
            if 1 in tiers:
                target_metrics.extend(TIER1_METRICS)
            if 2 in tiers:
                target_metrics.extend(TIER2_METRICS)
            if 3 in tiers:
                target_metrics.extend(TIER3_METRICS)

        # Filter to only valid slugs (discovered during discovery phase)
        if self._valid_slugs:
            target_slugs = [s for s in raw_slugs if s in self._valid_slugs]
            skipped = [s for s in raw_slugs if s not in self._valid_slugs]
            if skipped:
                logger.warning(f"  Skipping {len(skipped)} invalid slugs: {skipped}")
        else:
            target_slugs = raw_slugs

        total_combinations = len(target_slugs) * (len(target_metrics) + 1)  # +1 for OHLCV
        logger.info("=" * 60)
        logger.info("STARTING BULK DATA PULL")
        logger.info(f"  Tokens: {len(target_slugs)}")
        logger.info(f"  Metrics: {len(target_metrics)}")
        logger.info(f"  Years: {years_back}")
        logger.info(f"  Total metric/slug combinations: {total_combinations}")
        logger.info(f"  Estimated API calls: ~{total_combinations + len(target_slugs)}")
        logger.info("=" * 60)
        start = time.time()

        all_stats = {"metrics": {}, "ohlcv": {}, "fundamentals": {}}

        # Pull OHLCV first (most important for charts)
        logger.info("\n--- PHASE A: OHLCV Price Data ---")
        all_stats["ohlcv"] = await self.pull_ohlcv_for_tokens(target_slugs, years_back)

        # Pull fundamentals
        logger.info("\n--- PHASE B: Project Fundamentals ---")
        all_stats["fundamentals"] = await self.pull_fundamentals_for_tokens(target_slugs)

        # Pull each metric
        logger.info("\n--- PHASE C: Metric Timeseries ---")
        for mi, metric in enumerate(target_metrics):
            logger.info(f"\nMetric [{mi+1}/{len(target_metrics)}]: {metric}")
            metric_stats = await self.pull_metric_for_tokens(
                metric, target_slugs, years_back
            )
            all_stats["metrics"][metric] = metric_stats
            logger.info(f"  Done: {metric_stats['success']} success, "
                       f"{metric_stats['failed']} failed, "
                       f"{metric_stats['total_points']} points")

        elapsed = time.time() - start
        all_stats["total_elapsed_seconds"] = round(elapsed, 1)
        all_stats["total_api_calls"] = self._client.stats["total_requests"]
        all_stats["total_data_points"] = self._client.stats["total_data_points"]
        all_stats["cache_stats"] = self._cache.get_pull_stats()

        self._results["pull_stats"] = all_stats
        logger.info("\n" + "=" * 60)
        logger.info("BULK PULL COMPLETE")
        logger.info(f"  Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
        logger.info(f"  API calls: {self._client.stats['total_requests']}")
        logger.info(f"  Data points: {self._client.stats['total_data_points']}")
        logger.info(f"  Cache: {json.dumps(all_stats['cache_stats'], indent=2)}")
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
        Incremental daily refresh — only pull today's data.
        Much cheaper than full pull: ~1 API call per metric
        (uses batch queries where possible).
        """
        target_slugs = slugs or TOP_TOKENS
        target_metrics = metrics or (TIER1_METRICS + TIER2_METRICS)

        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        from_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")

        logger.info(f"DAILY REFRESH: {len(target_metrics)} metrics × {len(target_slugs)} tokens")
        start = time.time()
        stats = {"success": 0, "failed": 0, "total_points": 0}

        for slug in target_slugs:
            # Batch 5 metrics per request for efficiency
            for i in range(0, len(target_metrics), 5):
                batch = target_metrics[i:i+5]
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
                    logger.warning(f"  Refresh failed for {slug} batch {i}: {e}")

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
    # FULL REPORT
    # ================================================================

    def get_full_report(self) -> dict:
        """Get complete results from all phases."""
        return {
            **self._results,
            "client_stats": self._client.stats,
            "cache_stats": self._cache.get_pull_stats(),
        }
