"""
Smart Money Dashboard API.

FastAPI application providing REST endpoints for the
smart money tracking dashboard.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.cache import CacheManager
from core.nansen_client import NansenClient
from core.nansen_models import VALID_CHAINS
from .tracker import SmartMoneyTracker


# Global instances
_client: Optional[NansenClient] = None
_tracker: Optional[SmartMoneyTracker] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _client, _tracker

    # Initialize on startup
    cache = CacheManager()
    _client = NansenClient(cache=cache)
    await _client.__aenter__()
    _tracker = SmartMoneyTracker(_client)

    yield

    # Cleanup on shutdown
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

    # === Historical Data Endpoints ===

    @app.get("/api/v1/history/{chain}/{token_address}")
    async def get_token_history(
        chain: str,
        token_address: str,
        days: int = Query(default=30, ge=1, le=365),
    ):
        """
        Get historical smart money holdings for a token.

        Returns time-series data showing position building over time.
        Up to 365 days of historical data (4 years max available via API).
        """
        if not _tracker:
            raise HTTPException(500, "Tracker not initialized")

        if chain not in VALID_CHAINS:
            raise HTTPException(400, f"Invalid chain: {chain}. Valid: {VALID_CHAINS}")

        return await _tracker.get_token_history(chain, token_address, days)

    @app.get("/api/v1/transfers/{chain}/{token_address}")
    async def get_token_transfers(
        chain: str,
        token_address: str,
        days: int = Query(default=7, ge=1, le=30),
    ):
        """
        Get token transfer activity by smart money.

        Returns flow analysis including CEX deposits (exit signals) vs DEX activity.
        Useful for identifying accumulation/distribution patterns.
        """
        if not _tracker:
            raise HTTPException(500, "Tracker not initialized")

        if chain not in VALID_CHAINS:
            raise HTTPException(400, f"Invalid chain: {chain}. Valid: {VALID_CHAINS}")

        return await _tracker.get_token_transfers(chain, token_address, days)

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

    # === Health Check ===

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0",
        }

    return app


# Create the app instance
app = create_app()
