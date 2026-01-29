"""
Smart Money Dashboard API.

FastAPI application providing REST endpoints for the
smart money tracking dashboard.
"""

import asyncio
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
from core.nansen_client import NansenClient
from core.nansen_models import VALID_CHAINS
from core.santiment_client import SantimentClient
from core.santiment_cache import SantimentCache
from core.santiment_data_puller import (
    SantimentDataPuller,
    TOP_TOKENS,
    TIER1_METRICS,
    TIER2_METRICS,
    ALL_PROFILE_METRICS,
)
from .tracker import SmartMoneyTracker

logger = logging.getLogger(__name__)

# Global instances
_client: Optional[NansenClient] = None
_tracker: Optional[SmartMoneyTracker] = None
_san_client: Optional[SantimentClient] = None
_san_cache: Optional[SantimentCache] = None
_san_puller: Optional[SantimentDataPuller] = None
_san_pull_status: dict = {"status": "idle", "last_pull": None, "error": None}


async def _santiment_background_pull():
    """Background task: pull Santiment data on startup and refresh periodically."""
    global _san_pull_status
    if not _san_client or not _san_cache or not _san_puller:
        logger.warning("Santiment not configured, skipping background pull")
        _san_pull_status = {"status": "skipped", "reason": "SANTIMENT_API_KEY not set"}
        return

    # Initial pull
    try:
        _san_pull_status = {"status": "discovering", "started_at": datetime.now(timezone.utc).isoformat()}
        logger.info("Santiment: Starting discovery...")
        await _san_puller.run_full_discovery()

        _san_pull_status["status"] = "pulling"
        logger.info("Santiment: Starting bulk pull (Tier 1+2, 50 tokens, 3 years)...")
        await _san_puller.run_bulk_pull(
            slugs=TOP_TOKENS,
            years_back=3,
            tiers=[1, 2],
        )

        _san_pull_status = {
            "status": "ready",
            "last_pull": datetime.now(timezone.utc).isoformat(),
            "cache_stats": _san_cache.get_pull_stats(),
        }
        logger.info(f"Santiment: Initial pull complete. Cache: {_san_cache.get_pull_stats()}")
    except Exception as e:
        logger.error(f"Santiment: Initial pull failed: {e}")
        _san_pull_status = {"status": "error", "error": str(e)}

    # Periodic refresh every 4 hours
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
    global _client, _tracker, _san_client, _san_cache, _san_puller

    # Initialize Nansen
    cache = CacheManager()
    _client = NansenClient(cache=cache)
    await _client.__aenter__()
    _tracker = SmartMoneyTracker(_client)

    # Initialize Santiment (if key is available)
    san_task = None
    san_api_key = os.environ.get("SANTIMENT_API_KEY")
    if san_api_key:
        logger.info("Santiment API key found, initializing...")
        mem_cache = CacheManager()
        _san_cache = SantimentCache()
        _san_client = SantimentClient(api_key=san_api_key, cache=mem_cache)
        await _san_client.__aenter__()
        _san_puller = SantimentDataPuller(_san_client, _san_cache)
        # Launch background pull
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
    if _client:
        await _client.__aexit__(None, None, None)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Smart Money Dashboard",
        description="""
        Track smart money activity across crypto markets using Nansen data.

        ## Features
        - **Token Purchases**: Real-time view of what tokens are being bought
        - **Recent Trades**: Live feed of DEX trades by smart money
        - **Token Drilldown**: Deep dive into holder activity for any token

        ## Design
        WSJ-inspired: Clean, data-focused, intentional use of color
        """,
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
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
        """Serve the main dashboard HTML."""
        template_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "templates", "dashboard.html"
        )
        try:
            with open(template_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            return """
            <html>
            <head><title>Smart Money Dashboard</title></head>
            <body>
                <h1>Smart Money Dashboard</h1>
                <p>Dashboard template not found. API endpoints are available at /docs</p>
            </body>
            </html>
            """

    # === View 1: Token Purchases Overview ===

    @app.get("/api/v1/purchases")
    async def get_token_purchases(
        chains: str = Query(
            default="ethereum",
            description="Comma-separated blockchain networks (e.g., 'ethereum,solana')"
        ),
        sort_by: str = Query(
            default="net_flow_24h_usd",
            description="Sort field: net_flow_24h_usd, total_value_usd, smart_money_holders"
        ),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        """
        Get overview of tokens being purchased by smart money.

        Returns tokens sorted by accumulation signals with netflow data.
        """
        if not _tracker:
            raise HTTPException(500, "Tracker not initialized")

        chain_list = [c.strip() for c in chains.split(",")]

        # Validate chains
        invalid_chains = [c for c in chain_list if c not in VALID_CHAINS]
        if invalid_chains:
            raise HTTPException(400, f"Invalid chains: {invalid_chains}. Valid: {VALID_CHAINS}")

        return await _tracker.get_token_purchases(chain_list, sort_by, limit)

    # === Recent Trades Feed ===

    @app.get("/api/v1/trades")
    async def get_recent_trades(
        chains: str = Query(
            default="ethereum",
            description="Comma-separated blockchain networks"
        ),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        """
        Get real-time feed of DEX trades by smart money.

        Returns recent trades with buy/sell classification.
        """
        if not _tracker:
            raise HTTPException(500, "Tracker not initialized")

        chain_list = [c.strip() for c in chains.split(",")]

        # Validate chains
        invalid_chains = [c for c in chain_list if c not in VALID_CHAINS]
        if invalid_chains:
            raise HTTPException(400, f"Invalid chains: {invalid_chains}")

        return await _tracker.get_recent_trades(chain_list, limit)

    # === View 3: Token Drilldown ===

    @app.get("/api/v1/token/{chain}/{token_address}")
    async def get_token_drilldown(
        chain: str,
        token_address: str,
    ):
        """
        Get detailed holder activity for a specific token.

        Includes holder breakdown, flow intelligence, and recent trades.
        """
        if not _tracker:
            raise HTTPException(500, "Tracker not initialized")

        if chain not in VALID_CHAINS:
            raise HTTPException(400, f"Invalid chain: {chain}. Valid: {VALID_CHAINS}")

        return await _tracker.get_token_drilldown(chain, token_address)

    # === Market Overview ===

    @app.get("/api/v1/overview")
    async def get_market_overview(
        chains: str = Query(
            default="ethereum",
            description="Comma-separated blockchain networks"
        ),
    ):
        """
        Get comprehensive market overview with charts data.

        Returns aggregated stats, netflow charts, top tokens, and sector breakdown.
        """
        if not _tracker:
            raise HTTPException(500, "Tracker not initialized")

        chain_list = [c.strip() for c in chains.split(",")]

        invalid_chains = [c for c in chain_list if c not in VALID_CHAINS]
        if invalid_chains:
            raise HTTPException(400, f"Invalid chains: {invalid_chains}")

        return await _tracker.get_market_overview(chain_list)

    # === Perp Trades ===

    @app.get("/api/v1/perps")
    async def get_perp_trades(
        limit: int = Query(default=50, ge=1, le=200),
    ):
        """
        Get perpetual trades from Hyperliquid by smart money.

        Returns long/short sentiment and recent trades.
        """
        if not _tracker:
            raise HTTPException(500, "Tracker not initialized")

        return await _tracker.get_perp_trades(limit)

    # === Funds Overview ===

    @app.get("/api/v1/funds")
    async def get_funds_overview(
        chains: str = Query(
            default="ethereum",
            description="Comma-separated blockchain networks"
        ),
    ):
        """
        Get aggregated view of fund/institutional holdings.

        Shows combined positions, trades, and P/L for venture funds and hedge funds.
        """
        if not _tracker:
            raise HTTPException(500, "Tracker not initialized")

        chain_list = [c.strip() for c in chains.split(",")]

        invalid_chains = [c for c in chain_list if c not in VALID_CHAINS]
        if invalid_chains:
            raise HTTPException(400, f"Invalid chains: {invalid_chains}")

        return await _tracker.get_funds_overview(chain_list)

    # === Reference Endpoints ===

    @app.get("/api/v1/chains")
    async def get_supported_chains():
        """Get list of supported blockchain networks."""
        return {
            "chains": [
                {"id": "ethereum", "name": "Ethereum", "icon": "eth"},
                {"id": "solana", "name": "Solana", "icon": "sol"},
                {"id": "base", "name": "Base", "icon": "base"},
                {"id": "arbitrum", "name": "Arbitrum", "icon": "arb"},
                {"id": "bnb", "name": "BNB Chain", "icon": "bnb"},
                {"id": "polygon", "name": "Polygon", "icon": "matic"},
                {"id": "optimism", "name": "Optimism", "icon": "op"},
                {"id": "avalanche", "name": "Avalanche", "icon": "avax"},
            ]
        }

    @app.get("/api/v1/categories")
    async def get_smart_money_categories():
        """Get list of smart money categories with descriptions."""
        return {
            "categories": [
                {
                    "id": "Fund",
                    "name": "Fund",
                    "description": "Institutional funds and investment entities",
                },
                {
                    "id": "Smart Trader",
                    "name": "Smart Trader",
                    "description": "All-time profitable traders",
                },
                {
                    "id": "30D Smart Trader",
                    "name": "30D Smart Trader",
                    "description": "Top performers over last 30 days",
                },
                {
                    "id": "90D Smart Trader",
                    "name": "90D Smart Trader",
                    "description": "Top performers over last 90 days",
                },
                {
                    "id": "180D Smart Trader",
                    "name": "180D Smart Trader",
                    "description": "Top performers over last 180 days",
                },
                {
                    "id": "Smart HL Perps Trader",
                    "name": "Smart HL Perps",
                    "description": "Profitable perpetuals traders on Hyperliquid",
                },
            ]
        }

    # === Santiment API Endpoints ===

    @app.get("/api/v1/santiment/status")
    async def santiment_status():
        """Get Santiment data pull status and cache stats."""
        return {
            "pull_status": _san_pull_status,
            "cache_stats": _san_cache.get_pull_stats() if _san_cache else None,
            "client_stats": _san_client.stats if _san_client else None,
        }

    @app.get("/api/v1/santiment/projects")
    async def santiment_projects(
        min_marketcap: Optional[float] = Query(default=None, description="Minimum market cap filter"),
        limit: int = Query(default=100, ge=1, le=500),
    ):
        """Get all cached projects."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")
        projects = _san_cache.get_all_projects(min_marketcap)
        return {"projects": projects[:limit], "total": len(projects)}

    @app.get("/api/v1/santiment/profile/{slug}")
    async def santiment_profile(slug: str):
        """
        Get full TradFi-style profile for a token.
        Returns all cached metrics, OHLCV, and fundamentals.
        """
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")

        project = _san_cache.get_project(slug)
        if not project:
            raise HTTPException(404, f"Project '{slug}' not found in cache")

        # Get all cached timeseries for this slug
        metrics_data = {}
        for metric in ALL_PROFILE_METRICS:
            data = _san_cache.get_timeseries(metric, slug)
            if data:
                metrics_data[metric] = {
                    "data": data,
                    "count": len(data),
                    "latest": data[-1] if data else None,
                }

        # Get OHLCV
        ohlcv = _san_cache.get_ohlcv(slug)

        # Compute summary stats from latest values
        summary = {}
        for metric, info in metrics_data.items():
            if info["latest"] and info["latest"].get("value") is not None:
                summary[metric] = info["latest"]["value"]

        return {
            "project": project,
            "summary": summary,
            "metrics": metrics_data,
            "ohlcv": {"data": ohlcv, "count": len(ohlcv)},
        }

    @app.get("/api/v1/santiment/metric/{metric}")
    async def santiment_metric(
        metric: str,
        slug: str = Query(..., description="Token slug (e.g., 'bitcoin')"),
        from_date: Optional[str] = Query(default=None, description="Start date (ISO 8601)"),
        to_date: Optional[str] = Query(default=None, description="End date (ISO 8601)"),
    ):
        """Get timeseries data for a specific metric and token."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")

        data = _san_cache.get_timeseries(metric, slug, from_date, to_date)
        if not data:
            raise HTTPException(404, f"No data for metric '{metric}' on '{slug}'")

        return {
            "metric": metric,
            "slug": slug,
            "data": data,
            "count": len(data),
        }

    @app.get("/api/v1/santiment/ohlcv/{slug}")
    async def santiment_ohlcv(
        slug: str,
        from_date: Optional[str] = Query(default=None),
        to_date: Optional[str] = Query(default=None),
    ):
        """Get OHLCV price data for a token."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")

        data = _san_cache.get_ohlcv(slug, from_date, to_date)
        if not data:
            raise HTTPException(404, f"No OHLCV data for '{slug}'")

        return {"slug": slug, "data": data, "count": len(data)}

    @app.get("/api/v1/santiment/compare")
    async def santiment_compare(
        slugs: str = Query(..., description="Comma-separated slugs (e.g., 'bitcoin,ethereum,solana')"),
        metrics: str = Query(
            default="price_usd,mvrv_usd,nvt,daily_active_addresses",
            description="Comma-separated metrics",
        ),
    ):
        """Compare multiple tokens across multiple metrics (peer comparison)."""
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
                        "latest_date": data[-1]["datetime"],
                        "min_30d": min(values[-30:]) if len(values) >= 30 else min(values) if values else None,
                        "max_30d": max(values[-30:]) if len(values) >= 30 else max(values) if values else None,
                        "avg_30d": sum(values[-30:]) / len(values[-30:]) if len(values) >= 30 else sum(values) / len(values) if values else None,
                        "data_points": len(data),
                    }
                else:
                    comparison[slug][metric] = None

        return {"comparison": comparison, "slugs": slug_list, "metrics": metric_list}

    @app.get("/api/v1/santiment/valuation/{slug}")
    async def santiment_valuation(slug: str):
        """
        TradFi-style valuation summary for a token.
        Combines MVRV, NVT, realized value, and price data.
        """
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")

        valuation_metrics = [
            "mvrv_usd", "nvt", "realized_value_usd", "mean_realized_price_usd",
            "price_usd", "marketcap_usd", "volume_usd",
        ]

        result = {}
        for metric in valuation_metrics:
            data = _san_cache.get_timeseries(metric, slug)
            if data:
                values = [d["value"] for d in data if d.get("value") is not None]
                result[metric] = {
                    "current": values[-1] if values else None,
                    "avg_90d": sum(values[-90:]) / len(values[-90:]) if len(values) >= 90 else None,
                    "avg_365d": sum(values[-365:]) / len(values[-365:]) if len(values) >= 365 else None,
                    "min_365d": min(values[-365:]) if len(values) >= 365 else None,
                    "max_365d": max(values[-365:]) if len(values) >= 365 else None,
                    "percentile": None,  # computed below
                }
                # Compute where current sits in 1-year range
                if result[metric]["min_365d"] is not None and result[metric]["max_365d"] is not None:
                    range_val = result[metric]["max_365d"] - result[metric]["min_365d"]
                    if range_val > 0 and result[metric]["current"] is not None:
                        result[metric]["percentile"] = round(
                            (result[metric]["current"] - result[metric]["min_365d"]) / range_val * 100, 1
                        )

        # MVRV zones
        mvrv_current = result.get("mvrv_usd", {}).get("current")
        if mvrv_current is not None:
            if mvrv_current > 3.5:
                zone = "extremely_overvalued"
            elif mvrv_current > 2.5:
                zone = "overvalued"
            elif mvrv_current > 1.5:
                zone = "fair_to_high"
            elif mvrv_current > 1.0:
                zone = "fair"
            elif mvrv_current > 0.5:
                zone = "undervalued"
            else:
                zone = "extremely_undervalued"
            result["mvrv_zone"] = zone

        return {"slug": slug, "valuation": result}

    # === Health Check ===

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0",
            "santiment": _san_pull_status.get("status", "not_configured"),
        }

    return app


# Create the app instance
app = create_app()
