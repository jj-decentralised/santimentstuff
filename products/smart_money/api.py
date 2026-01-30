"""
Crypto Analytics Dashboard API.

FastAPI application serving Santiment on-chain data.
All pages are server-side rendered — no JavaScript required.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.cache import CacheManager
from core.santiment_client import SantimentClient
from core.santiment_cache import SantimentCache
from core.santiment_data_puller import (
    SantimentDataPuller,
    TOP_TOKENS,
    CORE_METRICS,
    TIER1_METRICS,
    TIER2_METRICS,
    ALL_PROFILE_METRICS,
)
from core.ssr_renderer import (
    render_briefing_page,
    render_explore_page,
    render_valuation_page,
    render_token_profile,
    render_sync_page,
    render_compare_page,
    render_screener_page,
    fmt_usd,
    fmt_pct,
    pct_class,
)

logger = logging.getLogger(__name__)

# Global instances
_san_client: Optional[SantimentClient] = None
_san_cache: Optional[SantimentCache] = None
_san_puller: Optional[SantimentDataPuller] = None
_san_pull_status: dict = {"status": "idle", "last_pull": None, "error": None}


async def _santiment_background_pull():
    """
    Background task: pull Santiment data in phases.

    Phase 1: Discover universe + lightweight pull (10 tokens, Tier 1, 1 year)
    Phase 2: Universe pull (ALL tokens, core metrics, 7 years)
    Phase 3: Deep pull (top 200 tokens, Tier 1+2, 7 years)
    Phase 4: Periodic refresh every 4 hours
    """
    global _san_pull_status
    if not _san_client or not _san_cache or not _san_puller:
        logger.warning("Santiment not configured, skipping background pull")
        _san_pull_status = {"status": "skipped", "reason": "SANTIMENT_API_KEY not set"}
        return

    logger.info("Santiment: Waiting 5s for app startup...")
    await asyncio.sleep(5)

    # Phase 1: Lightweight discovery + pull
    try:
        _san_pull_status = {
            "status": "phase1_discovery",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "phase": 1,
        }
        logger.info("Santiment Phase 1: Universe discovery...")
        await _san_puller.discover_universe()

        _san_pull_status["status"] = "phase1_pulling"
        _san_pull_status["universe_size"] = _san_puller.universe_size
        logger.info(f"Santiment Phase 1: Lightweight pull (10 tokens, Tier 1, 1 year). Universe: {_san_puller.universe_size}")
        phase1_stats = await _san_puller.run_lightweight_pull()

        _san_pull_status = {
            "status": "phase1_complete",
            "phase": 1,
            "last_pull": datetime.now(timezone.utc).isoformat(),
            "universe_size": _san_puller.universe_size,
            "cache_stats": _san_cache.get_pull_stats(),
            "phase1_stats": phase1_stats,
        }
        logger.info(f"Santiment Phase 1 complete: {phase1_stats.get('total_points', 0)} data points cached")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Santiment Phase 1 failed: {e}\n{tb}")
        _san_pull_status = {
            "status": "phase1_error",
            "error": str(e),
            "traceback": tb[-500:],
            "client_stats": _san_client.stats if _san_client else None,
        }
        await asyncio.sleep(30)

    # Phase 2: Universe pull (ALL tokens, core metrics, 7 years)
    try:
        _san_pull_status["status"] = "phase2_universe"
        _san_pull_status["phase"] = 2
        _san_pull_status["universe_size"] = _san_puller.universe_size
        logger.info(f"Santiment Phase 2: Universe pull ({_san_puller.universe_size} tokens, core metrics, 7 years)...")
        universe_stats = await _san_puller.run_universe_pull()

        _san_pull_status = {
            "status": "phase2_complete",
            "phase": 2,
            "last_pull": datetime.now(timezone.utc).isoformat(),
            "universe_size": _san_puller.universe_size,
            "cache_stats": _san_cache.get_pull_stats(),
            "universe_stats": {
                "total_points": universe_stats.get("total_points", 0),
                "elapsed_minutes": universe_stats.get("elapsed_minutes", 0),
            },
        }
        logger.info(f"Santiment Phase 2 complete. {universe_stats.get('total_points', 0)} points. Cache: {_san_cache.get_pull_stats()}")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Santiment Phase 2 failed: {e}\n{tb}")
        _san_pull_status["status"] = "phase2_error"
        _san_pull_status["phase2_error"] = str(e)
        _san_pull_status["cache_stats"] = _san_cache.get_pull_stats()

    # Phase 3: Deep pull (top 200, Tier 1+2, 7 years)
    try:
        _san_pull_status["status"] = "phase3_deep"
        _san_pull_status["phase"] = 3
        logger.info("Santiment Phase 3: Deep pull (top 200 tokens, Tier 1+2, 7 years)...")
        deep_stats = await _san_puller.run_deep_pull(top_n=200, tiers=[1, 2])

        _san_pull_status = {
            "status": "ready",
            "phase": "complete",
            "last_pull": datetime.now(timezone.utc).isoformat(),
            "universe_size": _san_puller.universe_size,
            "cache_stats": _san_cache.get_pull_stats(),
        }
        logger.info(f"Santiment Phase 3 complete. Cache: {_san_cache.get_pull_stats()}")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Santiment Phase 3 failed: {e}\n{tb}")
        _san_pull_status["status"] = "partial"
        _san_pull_status["phase3_error"] = str(e)
        _san_pull_status["cache_stats"] = _san_cache.get_pull_stats()

    # Phase 4: Periodic refresh
    while True:
        try:
            await asyncio.sleep(4 * 3600)
            logger.info("Santiment: Running periodic refresh...")
            _san_pull_status["status"] = "refreshing"
            await _san_puller.daily_refresh()
            _san_pull_status = {
                "status": "ready",
                "last_pull": datetime.now(timezone.utc).isoformat(),
                "universe_size": _san_puller.universe_size,
                "cache_stats": _san_cache.get_pull_stats(),
            }
            logger.info("Santiment: Refresh complete")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Santiment: Refresh failed: {e}")
            _san_pull_status["error"] = str(e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _san_client, _san_cache, _san_puller

    # Initialize Santiment
    san_task = None
    san_api_key = os.environ.get("SANTIMENT_API_KEY")
    if san_api_key:
        logger.info("Santiment API key found, initializing...")
        mem_cache = CacheManager()
        _san_cache = SantimentCache()
        _san_client = SantimentClient(api_key=san_api_key, cache=mem_cache)
        await _san_client.__aenter__()
        _san_puller = SantimentDataPuller(_san_client, _san_cache)
        san_task = asyncio.create_task(_santiment_background_pull())
    else:
        logger.warning("SANTIMENT_API_KEY not set, Santiment features disabled")

    yield

    # Cleanup
    if san_task:
        san_task.cancel()
        try:
            await san_task
        except asyncio.CancelledError:
            pass
    if _san_client:
        await _san_client.__aexit__(None, None, None)
    if _san_cache:
        _san_cache.close()


# ============================================================
# SHARED DATA HELPERS — with in-memory TTL cache
# ============================================================

KEY_METRICS = [
    "price_usd", "marketcap_usd", "volume_usd",
    "daily_active_addresses", "mvrv_usd", "nvt",
    "dev_activity", "exchange_balance", "network_growth",
    "transaction_volume",
]

SUMMARY_METRICS = [
    "price_usd", "marketcap_usd", "volume_usd",
    "daily_active_addresses", "mvrv_usd", "nvt",
]

# Bellwether tokens for economy-wide aggregate trends
BELLWETHER_SLUGS = [
    "bitcoin", "ethereum", "tether", "xrp", "binance-coin",
    "solana", "cardano", "dogecoin", "tron", "avalanche",
    "chainlink", "polkadot", "polygon", "litecoin", "uniswap",
    "stellar", "near-protocol", "internet-computer", "cosmos",
    "aave",
]

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500
_CACHE_TTL = 120  # seconds — recompute at most every 2 minutes

# In-memory result cache: {key: (timestamp, value)}
_result_cache: dict = {}


def _cached(key: str, builder, ttl: int = _CACHE_TTL):
    """Return cached result or compute and cache it."""
    import time as _time
    now = _time.time()
    entry = _result_cache.get(key)
    if entry and (now - entry[0]) < ttl:
        return entry[1]
    result = builder()
    _result_cache[key] = (now, result)
    return result


# ── Bulk token data ──────────────────────────────────────────

def _build_bulk_token_data(metrics_list: list[str]) -> list[dict]:
    """One SQL query per metric instead of per token×metric."""
    if not _san_cache:
        return []
    all_projects = _san_cache.get_all_projects()
    slug_map = {}
    for project in all_projects:
        slug = project.get("slug")
        if not slug:
            continue
        slug_map[slug] = {
            "slug": slug,
            "name": project.get("name", slug),
            "ticker": project.get("ticker", ""),
            "infrastructure": project.get("infrastructure", ""),
        }
    for metric in metrics_list:
        bulk = _san_cache.get_latest_values(metric)
        for slug, vals in bulk.items():
            if slug not in slug_map:
                continue
            latest = vals.get("latest")
            prev = vals.get("prev")
            slug_map[slug][metric] = latest
            if latest is not None and prev is not None and prev != 0:
                slug_map[slug][f"{metric}_change"] = round((latest - prev) / prev * 100, 2)
            else:
                slug_map[slug][f"{metric}_change"] = 0 if latest is not None else None
    tokens = [t for t in slug_map.values() if t.get("price_usd") is not None]
    tokens.sort(key=lambda x: x.get("marketcap_usd") or 0, reverse=True)
    return tokens


def _get_all_tokens() -> list[dict]:
    return _cached("all_tokens", lambda: _build_bulk_token_data(KEY_METRICS))


def _get_summary_tokens() -> list[dict]:
    return _cached("summary_tokens", lambda: _build_bulk_token_data(SUMMARY_METRICS))


# ── Economy-level aggregates ─────────────────────────────────

def _build_economy_briefing() -> dict:
    """
    Core economy briefing — answers:
      1. What regime are we in? (MVRV distribution, breadth)
      2. Where is capital flowing? (exchange balance, volume concentration)
      3. How healthy are networks? (aggregate DAA, dev activity, growth)
      4. What moved meaningfully? (on-chain signals, not just price noise)
      5. What's the valuation landscape? (zone distribution)
    """
    def _compute():
        tokens = _get_all_tokens()
        if not tokens:
            return {}

        # ── 1. Market regime ──
        total_mcap = sum(t.get("marketcap_usd") or 0 for t in tokens)
        total_vol = sum(t.get("volume_usd") or 0 for t in tokens)
        mvrv_vals = [t["mvrv_usd"] for t in tokens if t.get("mvrv_usd") is not None]
        avg_mvrv = sum(mvrv_vals) / len(mvrv_vals) if mvrv_vals else None
        pos = sum(1 for t in tokens if (t.get("price_usd_change") or 0) > 0)
        neg = sum(1 for t in tokens if (t.get("price_usd_change") or 0) < 0)
        flat = len(tokens) - pos - neg

        # ── 2. MVRV zone distribution ──
        zones = {"deep_value": 0, "undervalued": 0, "fair": 0, "elevated": 0, "overvalued": 0, "euphoria": 0}
        for v in mvrv_vals:
            if v < 0.7:
                zones["deep_value"] += 1
            elif v < 1.0:
                zones["undervalued"] += 1
            elif v < 1.5:
                zones["fair"] += 1
            elif v < 2.5:
                zones["elevated"] += 1
            elif v < 3.5:
                zones["overvalued"] += 1
            else:
                zones["euphoria"] += 1

        # ── 3. Capital flows — volume concentration + exchange balance ──
        top10_vol = sum(t.get("volume_usd") or 0 for t in tokens[:10])
        vol_concentration = (top10_vol / total_vol * 100) if total_vol > 0 else 0

        # Exchange balance changes (accumulation vs distribution signal)
        exch_tokens = [t for t in tokens if t.get("exchange_balance") is not None and t.get("exchange_balance_change") is not None]
        accum_count = sum(1 for t in exch_tokens if (t.get("exchange_balance_change") or 0) < -1)
        distrib_count = sum(1 for t in exch_tokens if (t.get("exchange_balance_change") or 0) > 1)

        # ── 4. Network health aggregates ──
        total_daa = sum(t.get("daily_active_addresses") or 0 for t in tokens)
        daa_with_change = [t for t in tokens if t.get("daily_active_addresses_change") is not None]
        avg_daa_change = (sum(t["daily_active_addresses_change"] for t in daa_with_change) / len(daa_with_change)) if daa_with_change else None

        dev_tokens = [t for t in tokens if t.get("dev_activity") is not None]
        total_dev = sum(t.get("dev_activity") or 0 for t in dev_tokens)
        dev_with_change = [t for t in dev_tokens if t.get("dev_activity_change") is not None]
        avg_dev_change = (sum(t["dev_activity_change"] for t in dev_with_change) / len(dev_with_change)) if dev_with_change else None

        growth_tokens = [t for t in tokens if t.get("network_growth") is not None]
        total_growth = sum(t.get("network_growth") or 0 for t in growth_tokens)

        # ── 5. Notable on-chain moves (signals, not just price) ──
        signals = []

        # Biggest DAA changes (network activity spikes)
        daa_movers = sorted(
            [t for t in tokens if t.get("daily_active_addresses_change") is not None and abs(t.get("daily_active_addresses_change") or 0) > 10],
            key=lambda t: abs(t.get("daily_active_addresses_change") or 0), reverse=True,
        )[:5]
        for t in daa_movers:
            ch = t["daily_active_addresses_change"]
            signals.append({
                "slug": t["slug"], "name": t["name"], "ticker": t["ticker"],
                "signal": "daa_spike" if ch > 0 else "daa_drop",
                "metric": "Active Addresses",
                "change": ch,
            })

        # Exchange balance shifts (accumulation/distribution)
        exch_movers = sorted(
            [t for t in exch_tokens if abs(t.get("exchange_balance_change") or 0) > 3],
            key=lambda t: abs(t.get("exchange_balance_change") or 0), reverse=True,
        )[:5]
        for t in exch_movers:
            ch = t["exchange_balance_change"]
            signals.append({
                "slug": t["slug"], "name": t["name"], "ticker": t["ticker"],
                "signal": "distribution" if ch > 0 else "accumulation",
                "metric": "Exchange Balance",
                "change": ch,
            })

        # Dev activity changes
        dev_movers = sorted(
            [t for t in dev_tokens if t.get("dev_activity_change") is not None and abs(t.get("dev_activity_change") or 0) > 15],
            key=lambda t: abs(t.get("dev_activity_change") or 0), reverse=True,
        )[:5]
        for t in dev_movers:
            ch = t["dev_activity_change"]
            signals.append({
                "slug": t["slug"], "name": t["name"], "ticker": t["ticker"],
                "signal": "dev_surge" if ch > 0 else "dev_decline",
                "metric": "Dev Activity",
                "change": ch,
            })

        # ── 6. Aggregate trend lines (for charts) ──
        trends = {}
        if _san_cache:
            for metric_key, label in [
                ("daily_active_addresses", "daa"),
                ("dev_activity", "dev"),
                ("network_growth", "growth"),
                ("volume_usd", "volume"),
            ]:
                data = _san_cache.get_aggregate_timeseries(metric_key, BELLWETHER_SLUGS, days=90)
                if data and len(data) > 5:
                    trends[label] = data

            # BTC price as market proxy
            btc_data = _san_cache.get_timeseries("price_usd", "bitcoin")
            if btc_data and len(btc_data) > 90:
                trends["btc_price"] = btc_data[-90:]
            elif btc_data:
                trends["btc_price"] = btc_data

            # BTC mcap trend
            btc_mcap = _san_cache.get_timeseries("marketcap_usd", "bitcoin")
            if btc_mcap and len(btc_mcap) > 90:
                trends["btc_mcap"] = btc_mcap[-90:]
            elif btc_mcap:
                trends["btc_mcap"] = btc_mcap

        # ── 7. Gainers / Losers ──
        valid = [t for t in tokens if t.get("price_usd_change") is not None and abs(t.get("price_usd_change", 0)) < 500]
        valid.sort(key=lambda x: x.get("price_usd_change", 0), reverse=True)
        gainers = valid[:10]
        losers = list(reversed(valid[-10:]))

        # ── 8. Top by various metrics ──
        top_volume = tokens[:10]
        top_daa = sorted([t for t in tokens if t.get("daily_active_addresses")],
                         key=lambda t: t.get("daily_active_addresses") or 0, reverse=True)[:10]
        top_dev = sorted([t for t in tokens if t.get("dev_activity")],
                         key=lambda t: t.get("dev_activity") or 0, reverse=True)[:10]

        return {
            # Regime
            "total_tokens": len(tokens),
            "total_mcap": total_mcap,
            "total_vol": total_vol,
            "avg_mvrv": avg_mvrv,
            "breadth": {"up": pos, "down": neg, "flat": flat},
            "mvrv_zones": zones,
            "mvrv_total": len(mvrv_vals),

            # Capital flows
            "vol_concentration_top10": vol_concentration,
            "accumulating": accum_count,
            "distributing": distrib_count,

            # Network health
            "total_daa": total_daa,
            "avg_daa_change": avg_daa_change,
            "total_dev": total_dev,
            "avg_dev_change": avg_dev_change,
            "total_growth": total_growth,

            # Signals
            "signals": signals[:15],

            # Trends (for charts)
            "trends": trends,

            # Movers
            "gainers": gainers,
            "losers": losers,

            # Top lists
            "top_volume": top_volume,
            "top_daa": top_daa,
            "top_dev": top_dev,

            # Full token list for heatmap/dominance
            "all_tokens": tokens,
        }

    return _cached("economy_briefing", _compute)


# ── Page-specific data builders ──────────────────────────────

def _build_token_list(page: int = 1, per_page: int = DEFAULT_PAGE_SIZE):
    tokens = _get_all_tokens()
    total = len(tokens)
    start = (page - 1) * per_page
    end = start + per_page
    page_tokens = tokens[start:end]
    # Sparklines only for visible page
    for t in page_tokens:
        price_data = _san_cache.get_timeseries("price_usd", t["slug"])
        if price_data and len(price_data) >= 7:
            t["sparkline_7d"] = price_data[-7:]
        elif price_data and len(price_data) >= 2:
            t["sparkline_7d"] = price_data[-len(price_data):]
        else:
            t["sparkline_7d"] = []
    return page_tokens, total


def _build_all_tokens_for_valuation():
    tokens = _get_all_tokens()
    return [t for t in tokens if t.get("mvrv_usd") is not None and t.get("price_usd") is not None]


def _build_profile_metrics(slug: str):
    metrics_data = {}
    for metric in ALL_PROFILE_METRICS:
        data = _san_cache.get_timeseries(metric, slug)
        if data:
            values = [d["value"] for d in data if d.get("value") is not None]
            metrics_data[metric] = {
                "data": data,
                "count": len(data),
                "latest": data[-1]["value"] if data else None,
                "latest_date": data[-1]["datetime"] if data else None,
                "min_365d": min(values[-365:]) if len(values) >= 30 else (min(values) if values else None),
                "max_365d": max(values[-365:]) if len(values) >= 30 else (max(values) if values else None),
                "avg_30d": round(sum(values[-30:]) / len(values[-30:]), 4) if len(values) >= 30 else None,
            }
    return metrics_data


def _build_screener_tokens(
    min_mcap=0, max_mcap=float("inf"),
    min_change=-999, max_change=999,
    sort_by="marketcap_usd", order="desc",
):
    tokens = _get_all_tokens()
    filtered = []
    for t in tokens:
        mcap = t.get("marketcap_usd") or 0
        if mcap < min_mcap or mcap > max_mcap:
            continue
        pct = t.get("price_usd_change", 0) or 0
        if pct < min_change or pct > max_change:
            continue
        filtered.append(t)
    filtered.sort(key=lambda x: x.get(sort_by) or 0, reverse=(order == "desc"))
    return filtered


def _build_comparison_data(slugs: list[str]):
    if not _san_cache:
        return []
    results = []
    for slug in slugs:
        project = _san_cache.get_project(slug)
        if not project:
            project = {"name": slug.replace("-", " ").title(), "ticker": slug.upper()[:5]}
        metrics = _build_profile_metrics(slug)
        results.append({
            "slug": slug,
            "name": project.get("name", slug),
            "ticker": project.get("ticker", ""),
            "metrics": metrics,
        })
    return results


# ============================================================
# APP FACTORY
# ============================================================

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Crypto Analytics Dashboard",
        description="TradFi-inspired on-chain analytics powered by Santiment",
        version="4.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    static_path = os.path.join(os.path.dirname(__file__), "..", "..", "static")
    if os.path.exists(static_path):
        app.mount("/static", StaticFiles(directory=static_path), name="static")

    # ============================================================
    # SERVER-RENDERED PAGES (no JS required)
    # ============================================================

    @app.get("/", response_class=HTMLResponse)
    async def get_briefing_page():
        """Economy briefing — the daily dashboard."""
        briefing = _build_economy_briefing()
        status = _san_pull_status.get("status", "unknown")
        cache_stats = _san_cache.get_pull_stats() if _san_cache else {}
        universe_size = _san_pull_status.get("universe_size", 0)
        return render_briefing_page(briefing, status, cache_stats, universe_size)

    @app.get("/explore", response_class=HTMLResponse)
    async def get_explore_page(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PAGE_SIZE, ge=10, le=MAX_PAGE_SIZE),
    ):
        """Full token explorer with pagination."""
        tokens, total = _build_token_list(page, per_page)
        return render_explore_page(tokens, page=page, per_page=per_page, total=total)

    @app.get("/valuation", response_class=HTMLResponse)
    async def get_valuation_page():
        """Valuation scanner — fully server-rendered."""
        if not _san_cache:
            return render_valuation_page([])
        enriched = _build_all_tokens_for_valuation()
        return render_valuation_page(enriched)

    @app.get("/sync", response_class=HTMLResponse)
    async def get_sync_page():
        """Sync status — fully server-rendered."""
        cache_stats = _san_cache.get_pull_stats() if _san_cache else {}
        client_stats = _san_client.stats if _san_client else {}
        return render_sync_page(_san_pull_status, cache_stats, client_stats)

    @app.get("/compare", response_class=HTMLResponse)
    async def get_compare_page(
        tokens: str = Query(default="bitcoin,ethereum,solana", description="Comma-separated slugs"),
    ):
        """Side-by-side token comparison with charts."""
        slug_list = [s.strip() for s in tokens.split(",") if s.strip()][:5]
        comparison_data = _build_comparison_data(slug_list)
        return render_compare_page(comparison_data)

    @app.get("/screener", response_class=HTMLResponse)
    async def get_screener_page(
        tier: str = Query(default="all", description="Market cap tier: mega, large, mid, small, micro, all"),
        min_change: float = Query(default=-999),
        max_change: float = Query(default=999),
        sort: str = Query(default="marketcap_usd"),
        order: str = Query(default="desc"),
    ):
        """Token screener with filters."""
        tier_ranges = {
            "mega": (100e9, float("inf")),
            "large": (10e9, 100e9),
            "mid": (1e9, 10e9),
            "small": (100e6, 1e9),
            "micro": (0, 100e6),
            "all": (0, float("inf")),
        }
        min_mcap, max_mcap = tier_ranges.get(tier, (0, float("inf")))
        tokens = _build_screener_tokens(min_mcap, max_mcap, min_change, max_change, sort, order)
        return render_screener_page(
            tokens, tier=tier, min_change=min_change, max_change=max_change,
            sort_by=sort, order=order,
        )

    @app.get("/token/{slug}", response_class=HTMLResponse)
    async def get_token_page(slug: str):
        """Token profile — fully server-rendered with deep metrics."""
        if not _san_cache:
            return HTMLResponse("<html><body><h1>Data not available yet</h1><a href='/'>Back</a></body></html>")

        project = _san_cache.get_project(slug)
        if not project:
            project = {"name": slug.replace("-", " ").title(), "ticker": slug.upper()[:5]}

        metrics = _build_profile_metrics(slug)
        if not metrics:
            return HTMLResponse(f"<html><body><h1>No data for {slug}</h1><p>Data may still be loading.</p><a href='/'>Back</a></body></html>")

        return render_token_profile(project, metrics, slug)

    # ============================================================
    # JSON API ENDPOINTS (for programmatic access)
    # ============================================================

    @app.get("/api/v1/market")
    async def get_market_overview(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PAGE_SIZE, ge=10, le=MAX_PAGE_SIZE),
    ):
        """JSON: all tokens with latest metrics (paginated)."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")
        tokens, total = _build_token_list(page, per_page)
        total_pages = (total + per_page - 1) // per_page
        return {
            "tokens": tokens,
            "count": len(tokens),
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "pull_status": _san_pull_status.get("status", "unknown"),
            "last_pull": _san_pull_status.get("last_pull"),
            "universe_size": _san_pull_status.get("universe_size", 0),
        }

    @app.get("/api/v1/profile/{slug}")
    async def get_token_profile_api(slug: str):
        """JSON: full token profile."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")
        project = _san_cache.get_project(slug)
        if not project:
            raise HTTPException(404, f"Project '{slug}' not found")
        metrics = _build_profile_metrics(slug)
        return {"project": project, "metrics": metrics}

    @app.get("/api/v1/metric/{metric}")
    async def get_metric(
        metric: str,
        slug: str = Query(..., description="Token slug"),
        from_date: Optional[str] = Query(default=None),
        to_date: Optional[str] = Query(default=None),
    ):
        """JSON: timeseries data for a specific metric."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")
        data = _san_cache.get_timeseries(metric, slug, from_date, to_date)
        return {"metric": metric, "slug": slug, "data": data, "count": len(data)}

    @app.get("/api/v1/valuation/{slug}")
    async def get_valuation(slug: str):
        """JSON: valuation summary."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")
        valuation_metrics = ["mvrv_usd", "nvt", "price_usd", "marketcap_usd", "volume_usd"]
        result = {}
        for metric in valuation_metrics:
            data = _san_cache.get_timeseries(metric, slug)
            if data:
                values = [d["value"] for d in data if d.get("value") is not None]
                result[metric] = {
                    "current": values[-1] if values else None,
                    "avg_90d": round(sum(values[-90:]) / len(values[-90:]), 2) if len(values) >= 90 else None,
                    "avg_365d": round(sum(values[-365:]) / len(values[-365:]), 2) if len(values) >= 365 else None,
                    "min_365d": min(values[-365:]) if len(values) >= 365 else None,
                    "max_365d": max(values[-365:]) if len(values) >= 365 else None,
                }
        return {"slug": slug, "valuation": result}

    # ============================================================
    # SYSTEM ENDPOINTS
    # ============================================================

    @app.get("/api/v1/status")
    async def get_status():
        """System status and pull progress."""
        db_path = _san_cache._db_path if _san_cache else None
        volume_mounted = os.path.isdir("/data")
        return {
            "pull_status": _san_pull_status,
            "cache_stats": _san_cache.get_pull_stats() if _san_cache else None,
            "client_stats": _san_client.stats if _san_client else None,
            "storage": {
                "db_path": db_path,
                "volume_mounted": volume_mounted,
                "persistent": db_path.startswith("/data") if db_path else False,
            },
        }

    @app.post("/api/v1/retry")
    async def retry_pull():
        """Trigger a data pull retry."""
        global _san_pull_status
        if not _san_client or not _san_puller:
            raise HTTPException(503, "Santiment not configured")
        if _san_pull_status.get("status") in ("phase1_pulling", "phase2_universe", "phase3_deep"):
            return {"message": "Pull already in progress"}
        asyncio.create_task(_santiment_background_pull())
        return {"message": "Pull retry triggered"}

    @app.get("/health")
    async def health_check():
        """Health check."""
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "santiment": _san_pull_status.get("status", "not_configured"),
            "universe_size": _san_pull_status.get("universe_size", 0),
        }

    return app


app = create_app()
