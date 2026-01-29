"""
Crypto Analytics Dashboard API.

FastAPI application serving Santiment on-chain data
for a TradFi-inspired token analytics dashboard.
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
    TIER1_METRICS,
    TIER2_METRICS,
    ALL_PROFILE_METRICS,
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

    Phase 1: Lightweight discovery + pull (10 tokens, Tier 1, 1 year)
    Phase 2: Full bulk pull (all tokens, Tier 1+2, 3 years)
    Phase 3: Periodic refresh every 4 hours
    """
    global _san_pull_status
    if not _san_client or not _san_cache or not _san_puller:
        logger.warning("Santiment not configured, skipping background pull")
        _san_pull_status = {"status": "skipped", "reason": "SANTIMENT_API_KEY not set"}
        return

    logger.info("Santiment: Waiting 5s for app startup...")
    await asyncio.sleep(5)

    # Phase 1: Lightweight pull
    try:
        _san_pull_status = {
            "status": "phase1_discovery",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "phase": 1,
        }
        logger.info("Santiment Phase 1: Lightweight discovery...")
        await _san_puller.run_lightweight_discovery()

        _san_pull_status["status"] = "phase1_pulling"
        logger.info("Santiment Phase 1: Pulling core data (10 tokens, Tier 1, 1 year)...")
        phase1_stats = await _san_puller.run_lightweight_pull()

        _san_pull_status = {
            "status": "phase1_complete",
            "phase": 1,
            "last_pull": datetime.now(timezone.utc).isoformat(),
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

    # Phase 2: Full bulk pull
    try:
        _san_pull_status["status"] = "phase2_pulling"
        _san_pull_status["phase"] = 2
        logger.info("Santiment Phase 2: Full bulk pull (all tokens, Tier 1+2, 3 years)...")
        await _san_puller.run_bulk_pull(
            slugs=TOP_TOKENS,
            years_back=3,
            tiers=[1, 2],
        )

        _san_pull_status = {
            "status": "ready",
            "phase": "complete",
            "last_pull": datetime.now(timezone.utc).isoformat(),
            "cache_stats": _san_cache.get_pull_stats(),
        }
        logger.info(f"Santiment Phase 2 complete. Cache: {_san_cache.get_pull_stats()}")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Santiment Phase 2 failed: {e}\n{tb}")
        _san_pull_status["status"] = "partial"
        _san_pull_status["phase2_error"] = str(e)
        _san_pull_status["cache_stats"] = _san_cache.get_pull_stats()

    # Phase 3: Periodic refresh
    while True:
        try:
            await asyncio.sleep(4 * 3600)
            logger.info("Santiment: Running periodic refresh...")
            _san_pull_status["status"] = "refreshing"
            await _san_puller.daily_refresh()
            _san_pull_status = {
                "status": "ready",
                "last_pull": datetime.now(timezone.utc).isoformat(),
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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Crypto Analytics Dashboard",
        description="TradFi-inspired on-chain analytics powered by Santiment",
        version="2.0.0",
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

    # === Dashboard HTML ===

    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard():
        """Serve the main dashboard HTML with pre-loaded market data."""
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "templates", "dashboard.html"
        )
        try:
            with open(template_path, "r") as f:
                html = f.read()
        except FileNotFoundError:
            return "<html><body><h1>Dashboard template not found</h1></body></html>"

        # Inject market data so JS doesn't need to fetch on first load
        preload_data = {"tokens": [], "count": 0, "pull_status": "loading", "last_pull": None}
        if _san_cache:
            try:
                key_metrics = [
                    "price_usd", "marketcap_usd", "volume_usd",
                    "daily_active_addresses", "mvrv_usd", "nvt",
                    "dev_activity", "exchange_balance", "network_growth",
                    "transaction_volume",
                ]
                tokens = []
                for slug in TOP_TOKENS:
                    project = _san_cache.get_project(slug)
                    token_data = {
                        "slug": slug,
                        "name": project.get("name", slug) if project else slug,
                        "ticker": project.get("ticker", "") if project else "",
                    }
                    for metric in key_metrics:
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
                preload_data = {
                    "tokens": tokens,
                    "count": len(tokens),
                    "pull_status": _san_pull_status.get("status", "unknown"),
                    "last_pull": _san_pull_status.get("last_pull"),
                }
            except Exception as e:
                logger.error(f"Error pre-loading market data: {e}")

        # Inject data as a script tag before dashboard.js
        data_script = f'<script>window.__MARKET_DATA__ = {json.dumps(preload_data)};</script>\n'
        html = html.replace(
            '<script src="/static/js/dashboard.js"></script>',
            data_script + '<script src="/static/js/dashboard.js"></script>',
        )
        return html

    # === Market Overview (all tokens with latest metrics) ===

    @app.get("/api/v1/market")
    async def get_market_overview():
        """
        Get all tokens with their latest metric values.
        Returns a compact table-ready format for the dashboard.
        """
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")

        key_metrics = [
            "price_usd", "marketcap_usd", "volume_usd",
            "daily_active_addresses", "mvrv_usd", "nvt",
            "dev_activity", "exchange_balance", "network_growth",
            "transaction_volume",
        ]

        tokens = []
        for slug in TOP_TOKENS:
            project = _san_cache.get_project(slug)
            token_data = {
                "slug": slug,
                "name": project.get("name", slug) if project else slug,
                "ticker": project.get("ticker", "") if project else "",
            }

            for metric in key_metrics:
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

            # Only include tokens that have at least price data
            if token_data.get("price_usd") is not None:
                tokens.append(token_data)

        # Sort by market cap descending
        tokens.sort(key=lambda x: x.get("marketcap_usd") or 0, reverse=True)

        return {
            "tokens": tokens,
            "count": len(tokens),
            "pull_status": _san_pull_status.get("status", "unknown"),
            "last_pull": _san_pull_status.get("last_pull"),
        }

    # === Token Profile ===

    @app.get("/api/v1/profile/{slug}")
    async def get_token_profile(slug: str):
        """Full TradFi-style profile for a token with all cached metrics."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")

        project = _san_cache.get_project(slug)
        if not project:
            raise HTTPException(404, f"Project '{slug}' not found")

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

        # Valuation zones
        valuation = {}
        mvrv = metrics_data.get("mvrv_usd", {}).get("latest")
        if mvrv is not None:
            if mvrv > 3.5: valuation["mvrv_zone"] = "extremely_overvalued"
            elif mvrv > 2.5: valuation["mvrv_zone"] = "overvalued"
            elif mvrv > 1.5: valuation["mvrv_zone"] = "fair_to_high"
            elif mvrv > 1.0: valuation["mvrv_zone"] = "fair"
            elif mvrv > 0.5: valuation["mvrv_zone"] = "undervalued"
            else: valuation["mvrv_zone"] = "extremely_undervalued"
            valuation["mvrv_value"] = mvrv

        return {
            "project": project,
            "metrics": metrics_data,
            "valuation": valuation,
        }

    # === Comparison ===

    @app.get("/api/v1/compare")
    async def compare_tokens(
        slugs: str = Query(..., description="Comma-separated slugs"),
        metrics: str = Query(
            default="price_usd,mvrv_usd,nvt,daily_active_addresses",
            description="Comma-separated metrics",
        ),
    ):
        """Compare multiple tokens across metrics."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")

        slug_list = [s.strip() for s in slugs.split(",")]
        metric_list = [m.strip() for m in metrics.split(",")]

        comparison = {}
        for slug in slug_list:
            comparison[slug] = {}
            for metric in metric_list:
                data = _san_cache.get_timeseries(metric, slug)
                if data and data[-1].get("value") is not None:
                    values = [d["value"] for d in data if d.get("value") is not None]
                    comparison[slug][metric] = {
                        "latest": data[-1]["value"],
                        "avg_30d": round(sum(values[-30:]) / len(values[-30:]), 4) if len(values) >= 30 else None,
                        "data_points": len(data),
                    }
                else:
                    comparison[slug][metric] = None

        return {"comparison": comparison, "slugs": slug_list, "metrics": metric_list}

    # === Metric Timeseries ===

    @app.get("/api/v1/metric/{metric}")
    async def get_metric(
        metric: str,
        slug: str = Query(..., description="Token slug"),
        from_date: Optional[str] = Query(default=None),
        to_date: Optional[str] = Query(default=None),
    ):
        """Get timeseries data for a specific metric and token."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")

        data = _san_cache.get_timeseries(metric, slug, from_date, to_date)
        return {"metric": metric, "slug": slug, "data": data, "count": len(data)}

    # === Valuation ===

    @app.get("/api/v1/valuation/{slug}")
    async def get_valuation(slug: str):
        """TradFi-style valuation summary with MVRV/NVT zones."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")

        valuation_metrics = [
            "mvrv_usd", "nvt", "price_usd", "marketcap_usd", "volume_usd",
        ]

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
                    "percentile": None,
                }
                if result[metric]["min_365d"] is not None and result[metric]["max_365d"] is not None:
                    r = result[metric]["max_365d"] - result[metric]["min_365d"]
                    if r > 0 and result[metric]["current"] is not None:
                        result[metric]["percentile"] = round(
                            (result[metric]["current"] - result[metric]["min_365d"]) / r * 100, 1
                        )

        mvrv = result.get("mvrv_usd", {}).get("current")
        if mvrv is not None:
            if mvrv > 3.5: result["mvrv_zone"] = "extremely_overvalued"
            elif mvrv > 2.5: result["mvrv_zone"] = "overvalued"
            elif mvrv > 1.5: result["mvrv_zone"] = "fair_to_high"
            elif mvrv > 1.0: result["mvrv_zone"] = "fair"
            elif mvrv > 0.5: result["mvrv_zone"] = "undervalued"
            else: result["mvrv_zone"] = "extremely_undervalued"

        return {"slug": slug, "valuation": result}

    # === System Endpoints ===

    @app.get("/api/v1/status")
    async def get_status():
        """Get system status and data pull progress."""
        return {
            "pull_status": _san_pull_status,
            "cache_stats": _san_cache.get_pull_stats() if _san_cache else None,
            "client_stats": _san_client.stats if _san_client else None,
        }

    @app.post("/api/v1/retry")
    async def retry_pull():
        """Manually trigger a data pull retry."""
        global _san_pull_status
        if not _san_client or not _san_puller:
            raise HTTPException(503, "Santiment not configured")
        if _san_pull_status.get("status") in ("phase1_pulling", "phase2_pulling"):
            return {"message": "Pull already in progress"}
        asyncio.create_task(_santiment_background_pull())
        return {"message": "Pull retry triggered"}

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "santiment": _san_pull_status.get("status", "not_configured"),
        }

    return app


app = create_app()
