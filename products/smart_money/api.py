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
    render_market_page,
    render_valuation_page,
    render_token_profile,
    render_sync_page,
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
# SHARED DATA HELPERS
# ============================================================

KEY_METRICS = [
    "price_usd", "marketcap_usd", "volume_usd",
    "daily_active_addresses", "mvrv_usd", "nvt",
    "dev_activity", "exchange_balance", "network_growth",
    "transaction_volume",
]

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


def _build_token_list(page: int = 1, per_page: int = DEFAULT_PAGE_SIZE):
    """Build the market token list from cache with pagination."""
    if not _san_cache:
        return [], 0

    # Get all projects from cache sorted by market cap
    all_projects = _san_cache.get_all_projects()

    tokens = []
    for project in all_projects:
        slug = project.get("slug")
        if not slug:
            continue

        token_data = {
            "slug": slug,
            "name": project.get("name", slug),
            "ticker": project.get("ticker", ""),
        }

        for metric in KEY_METRICS:
            data = _san_cache.get_timeseries(metric, slug)
            if data and len(data) >= 2:
                latest = data[-1]["value"]
                prev = data[-2]["value"]
                change_pct = ((latest - prev) / prev * 100) if prev and prev != 0 else 0
                token_data[metric] = latest
                token_data[f"{metric}_change"] = round(change_pct, 2)
            elif data and len(data) == 1:
                token_data[metric] = data[-1]["value"]
                token_data[f"{metric}_change"] = 0
            else:
                token_data[metric] = None
                token_data[f"{metric}_change"] = None

        if token_data.get("price_usd") is not None:
            tokens.append(token_data)

    tokens.sort(key=lambda x: x.get("marketcap_usd") or 0, reverse=True)
    total = len(tokens)

    # Apply pagination
    start = (page - 1) * per_page
    end = start + per_page
    return tokens[start:end], total


def _build_all_tokens_for_valuation():
    """Build token list with valuation data (no pagination, limited to those with MVRV/NVT)."""
    if not _san_cache:
        return []

    all_projects = _san_cache.get_all_projects()
    tokens = []

    for project in all_projects:
        slug = project.get("slug")
        if not slug:
            continue

        token_data = {
            "slug": slug,
            "name": project.get("name", slug),
            "ticker": project.get("ticker", ""),
        }

        for metric in KEY_METRICS:
            data = _san_cache.get_timeseries(metric, slug)
            if data and len(data) >= 2:
                latest = data[-1]["value"]
                prev = data[-2]["value"]
                change_pct = ((latest - prev) / prev * 100) if prev and prev != 0 else 0
                token_data[metric] = latest
                token_data[f"{metric}_change"] = round(change_pct, 2)
            elif data and len(data) == 1:
                token_data[metric] = data[-1]["value"]
                token_data[f"{metric}_change"] = 0
            else:
                token_data[metric] = None
                token_data[f"{metric}_change"] = None

        if token_data.get("mvrv_usd") is None and token_data.get("nvt") is None:
            continue
        if token_data.get("price_usd") is None:
            continue

        # Pull 90d and 365d averages for MVRV
        mvrv_data = _san_cache.get_timeseries("mvrv_usd", slug)
        if mvrv_data:
            vals = [d["value"] for d in mvrv_data if d.get("value") is not None]
            token_data["mvrv_90d"] = round(sum(vals[-90:]) / len(vals[-90:]), 4) if len(vals) >= 90 else None
            token_data["mvrv_365d"] = round(sum(vals[-365:]) / len(vals[-365:]), 4) if len(vals) >= 365 else None

        tokens.append(token_data)

    tokens.sort(key=lambda x: x.get("marketcap_usd") or 0, reverse=True)
    return tokens


def _build_profile_metrics(slug: str):
    """Build full metrics dict for a token profile."""
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
    async def get_market_page(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PAGE_SIZE, ge=10, le=MAX_PAGE_SIZE),
    ):
        """Market overview — fully server-rendered with pagination."""
        tokens, total = _build_token_list(page, per_page)
        status = _san_pull_status.get("status", "unknown")
        last_pull = _san_pull_status.get("last_pull")
        universe_size = _san_pull_status.get("universe_size", 0)
        cache_stats = _san_cache.get_pull_stats() if _san_cache else {}
        return render_market_page(
            tokens, status, last_pull,
            page=page, per_page=per_page, total=total,
            universe_size=universe_size, cache_stats=cache_stats,
        )

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
        return {
            "pull_status": _san_pull_status,
            "cache_stats": _san_cache.get_pull_stats() if _san_cache else None,
            "client_stats": _san_client.stats if _san_client else None,
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
