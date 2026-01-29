#!/usr/bin/env python3
"""
Santiment API Stress Test & Data Pull Runner.

Usage:
    # Discovery only (maps API surface, ~30 API calls)
    SANTIMENT_API_KEY=your_key python -m scripts.santiment_stress_test discover

    # Stress test (measures limits, ~100 API calls)
    SANTIMENT_API_KEY=your_key python -m scripts.santiment_stress_test stress

    # Bulk pull tier 1 metrics for top 50 tokens, 3 years
    SANTIMENT_API_KEY=your_key python -m scripts.santiment_stress_test pull --tiers 1 --tokens 50 --years 3

    # Full pull: all tiers, all tokens, 5 years
    SANTIMENT_API_KEY=your_key python -m scripts.santiment_stress_test pull --tiers 1,2,3 --tokens 50 --years 5

    # Daily incremental refresh
    SANTIMENT_API_KEY=your_key python -m scripts.santiment_stress_test refresh

    # Run everything: discover → stress test → pull
    SANTIMENT_API_KEY=your_key python -m scripts.santiment_stress_test all
"""

import asyncio
import argparse
import json
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.santiment_client import SantimentClient
from core.santiment_cache import SantimentCache
from core.santiment_data_puller import (
    SantimentDataPuller,
    TOP_TOKENS,
    TIER1_METRICS,
    TIER2_METRICS,
    TIER3_METRICS,
)
from core.cache import CacheManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def print_results(data: dict, indent: int = 0):
    """Pretty print nested results."""
    prefix = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            print(f"{prefix}{key}:")
            print_results(value, indent + 1)
        elif isinstance(value, list) and len(value) > 10:
            print(f"{prefix}{key}: [{len(value)} items]")
            for item in value[:3]:
                print(f"{prefix}  - {item}")
            print(f"{prefix}  ... and {len(value)-3} more")
        else:
            print(f"{prefix}{key}: {value}")


async def run_discover(puller: SantimentDataPuller):
    print_section("PHASE 1: API DISCOVERY")
    results = await puller.run_full_discovery()
    print("\n--- Discovery Results ---")
    print_results(results)
    return results


async def run_stress_test(puller: SantimentDataPuller):
    print_section("PHASE 2: API STRESS TEST")
    results = await puller.run_stress_test()

    print("\n--- Stress Test Summary ---")
    print(f"Total API calls: {results.get('total_api_calls', 'N/A')}")
    print(f"Total data points: {results.get('total_data_points_fetched', 'N/A')}")
    print(f"Total time: {results.get('total_elapsed_seconds', 'N/A')}s")

    # Individual metric results
    print("\n--- Per-Metric Results ---")
    print(f"{'Metric':<45} {'Points':>8} {'Time(ms)':>10} {'Status':>8}")
    print("-" * 75)
    for test in results.get("individual_metrics", []):
        print(f"{test['metric']:<45} {test['data_points']:>8} {test['response_time_ms']:>10} {test['status']:>8}")

    # Batch query
    batch = results.get("batch_query", {})
    print(f"\nBatch query (5 metrics): {batch.get('total_data_points', 0)} points in {batch.get('response_time_ms', 0)}ms")

    # Max history
    hist = results.get("max_history", {})
    print(f"Max history: {hist.get('years_of_data', 'N/A')} years ({hist.get('data_points', 0)} points)")
    print(f"  Earliest: {hist.get('earliest_date', 'N/A')}")

    # Rate burst
    burst = results.get("rate_burst", {})
    print(f"Rate burst ({burst.get('burst_count', 0)} concurrent): "
          f"{burst.get('successes', 0)} success, {burst.get('requests_per_second', 0)} req/s")

    # OHLCV
    ohlcv = results.get("ohlcv", {})
    print(f"OHLCV: {ohlcv.get('data_points', 0)} points, {ohlcv.get('years', 0)} years")

    # Multi-slug
    multi = results.get("multi_slug", {})
    print(f"Multi-slug (50 tokens): {multi.get('successes', 0)}/{multi.get('tested', 0)} returned data")
    if multi.get("failed_slugs"):
        print(f"  Failed slugs: {multi['failed_slugs']}")

    return results


async def run_bulk_pull(puller: SantimentDataPuller, tiers: list[int], num_tokens: int, years: int):
    print_section("PHASE 3: BULK DATA PULL")
    slugs = TOP_TOKENS[:num_tokens]
    print(f"Pulling: {len(slugs)} tokens × {sum(len(TIER1_METRICS) * (1 in tiers) + len(TIER2_METRICS) * (2 in tiers) + len(TIER3_METRICS) * (3 in tiers) for _ in [0])} metrics × {years} years")

    results = await puller.run_bulk_pull(
        slugs=slugs,
        years_back=years,
        tiers=tiers,
    )

    print("\n--- Bulk Pull Summary ---")
    print(f"Time: {results.get('total_elapsed_seconds', 0):.1f}s ({results.get('total_elapsed_seconds', 0)/60:.1f} min)")
    print(f"API calls: {results.get('total_api_calls', 0)}")
    print(f"Data points: {results.get('total_data_points', 0)}")

    cache_stats = results.get("cache_stats", {})
    print(f"\n--- Cache State ---")
    print(f"Timeseries rows: {cache_stats.get('timeseries_rows', 0):,}")
    print(f"OHLCV rows: {cache_stats.get('ohlcv_rows', 0):,}")
    print(f"Projects: {cache_stats.get('projects_cached', 0)}")
    print(f"DB size: {cache_stats.get('db_size_mb', 0):.1f} MB")

    # Per-metric breakdown
    print(f"\n--- Per-Metric Pull Results ---")
    print(f"{'Metric':<50} {'OK':>5} {'Fail':>5} {'Points':>10}")
    print("-" * 75)
    for metric, stats in results.get("metrics", {}).items():
        print(f"{metric:<50} {stats['success']:>5} {stats['failed']:>5} {stats['total_points']:>10}")

    return results


async def run_refresh(puller: SantimentDataPuller):
    print_section("DAILY REFRESH")
    results = await puller.daily_refresh()
    print(f"Refresh complete: {results['total_points']} points in {results['elapsed_seconds']}s")
    return results


async def main():
    parser = argparse.ArgumentParser(description="Santiment API Stress Test & Data Puller")
    parser.add_argument("mode", choices=["discover", "stress", "pull", "refresh", "all"],
                       help="Operation mode")
    parser.add_argument("--tiers", default="1,2", help="Metric tiers to pull (comma-separated: 1,2,3)")
    parser.add_argument("--tokens", type=int, default=50, help="Number of top tokens to pull")
    parser.add_argument("--years", type=int, default=3, help="Years of history to pull")
    parser.add_argument("--output", default=None, help="Save results to JSON file")

    args = parser.parse_args()
    tiers = [int(t) for t in args.tiers.split(",")]

    # Initialize
    mem_cache = CacheManager()
    db_cache = SantimentCache()

    try:
        async with SantimentClient(cache=mem_cache) as client:
            puller = SantimentDataPuller(client, db_cache)
            all_results = {}

            if args.mode in ("discover", "all"):
                all_results["discovery"] = await run_discover(puller)

            if args.mode in ("stress", "all"):
                all_results["stress_test"] = await run_stress_test(puller)

            if args.mode in ("pull", "all"):
                all_results["bulk_pull"] = await run_bulk_pull(puller, tiers, args.tokens, args.years)

            if args.mode == "refresh":
                all_results["refresh"] = await run_refresh(puller)

            # Final stats
            print_section("FINAL SUMMARY")
            report = puller.get_full_report()
            print(f"Client stats: {json.dumps(report['client_stats'], indent=2)}")
            print(f"Cache stats: {json.dumps(report['cache_stats'], indent=2)}")

            # Save results
            if args.output:
                with open(args.output, "w") as f:
                    json.dump(all_results, f, indent=2, default=str)
                print(f"\nResults saved to {args.output}")

    except ValueError as e:
        print(f"\nERROR: {e}")
        print("Set your API key: export SANTIMENT_API_KEY=your_key_here")
        sys.exit(1)
    finally:
        db_cache.close()


if __name__ == "__main__":
    asyncio.run(main())
