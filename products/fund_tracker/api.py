"""FastAPI application for Fund Portfolio Tracker."""

import os
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.arkham_client import ArkhamClient
from core.cache import CacheManager
from .tracker import FundTracker


# Global instances
_client: ArkhamClient | None = None
_tracker: FundTracker | None = None
_cache: CacheManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global _client, _tracker, _cache

    # Startup
    api_key = os.environ.get("ARKHAM_API_KEY", "")
    _cache = CacheManager()
    _client = ArkhamClient(api_key=api_key, cache=_cache)
    await _client.connect()
    _tracker = FundTracker(_client)

    yield

    # Shutdown
    if _client:
        await _client.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Fund Portfolio Tracker",
        description="Track crypto fund holdings, cost basis, and P/L",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files and templates
    app.mount("/static", StaticFiles(directory="static"), name="static")
    templates = Jinja2Templates(directory="templates")

    # === Page Routes ===

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        """Serve the main dashboard."""
        return templates.TemplateResponse("dashboard.html", {"request": request})

    # === API Routes ===

    @app.get("/api/v1/funds")
    async def list_funds():
        """Get list of available funds."""
        if not _tracker:
            raise HTTPException(status_code=503, detail="Service not ready")

        funds = await _tracker.get_available_funds()
        return {
            "funds": [
                {
                    "id": f.id,
                    "name": f.name,
                    "type": f.type,
                    "website": f.website,
                    "twitter": f.twitter,
                    "tags": f.tags,
                }
                for f in funds
            ]
        }

    @app.get("/api/v1/fund/{entity_id}")
    async def get_fund_info(entity_id: str):
        """Get fund information."""
        if not _tracker:
            raise HTTPException(status_code=503, detail="Service not ready")

        fund = await _client.get_entity(entity_id)
        if not fund:
            raise HTTPException(status_code=404, detail="Fund not found")

        return {
            "id": fund.id,
            "name": fund.name,
            "type": fund.type,
            "website": fund.website,
            "twitter": fund.twitter,
            "tags": fund.tags,
        }

    @app.get("/api/v1/fund/{entity_id}/holdings")
    async def get_fund_holdings(entity_id: str):
        """Get current holdings for a fund."""
        if not _tracker:
            raise HTTPException(status_code=503, detail="Service not ready")

        holdings = await _tracker.get_fund_holdings(entity_id)
        total_value = sum(h.value_usd for h in holdings)

        return {
            "entity_id": entity_id,
            "total_value_usd": total_value,
            "holdings": [
                {
                    "token_id": h.token_id,
                    "name": h.name,
                    "symbol": h.symbol,
                    "chain": h.chain,
                    "balance": h.balance,
                    "price": h.price,
                    "value_usd": h.value_usd,
                    "pct_of_portfolio": (h.value_usd / total_value * 100) if total_value > 0 else 0,
                }
                for h in holdings
            ],
        }

    @app.get("/api/v1/fund/{entity_id}/portfolio")
    async def get_fund_portfolio(entity_id: str):
        """Get complete portfolio with cost basis and P/L."""
        if not _tracker:
            raise HTTPException(status_code=503, detail="Service not ready")

        portfolio = await _tracker.get_full_portfolio(entity_id)
        if not portfolio:
            raise HTTPException(status_code=404, detail="Fund not found")

        return {
            "fund": {
                "id": portfolio.fund.id,
                "name": portfolio.fund.name,
                "type": portfolio.fund.type,
            },
            "total_value_usd": portfolio.total_value_usd,
            "total_cost_basis": portfolio.total_cost_basis,
            "total_unrealized_pnl": portfolio.total_unrealized_pnl,
            "total_pnl_pct": portfolio.total_pnl_pct,
            "holdings": [
                {
                    "token_id": h.token_id,
                    "name": h.name,
                    "symbol": h.symbol,
                    "chain": h.chain,
                    "balance": h.balance,
                    "price": h.price,
                    "value_usd": h.value_usd,
                }
                for h in portfolio.holdings
            ],
            "pnl_summary": [
                {
                    "token_id": p.token_id,
                    "symbol": p.symbol,
                    "current_value": p.current_value,
                    "cost_basis": p.cost_basis,
                    "unrealized_pnl": p.unrealized_pnl,
                    "unrealized_pnl_pct": p.unrealized_pnl_pct,
                    "realized_pnl": p.realized_pnl,
                }
                for p in portfolio.pnl_summary
            ],
        }

    @app.get("/api/v1/fund/{entity_id}/transfers")
    async def get_fund_transfers(entity_id: str, limit: int = 50):
        """Get recent transfers for a fund."""
        if not _tracker:
            raise HTTPException(status_code=503, detail="Service not ready")

        activity = await _tracker.get_recent_activity(entity_id, limit=limit)
        return {"entity_id": entity_id, "transfers": activity}

    @app.get("/api/v1/fund/{entity_id}/flows")
    async def get_fund_flows(entity_id: str):
        """Get historical flow data for a fund."""
        if not _tracker:
            raise HTTPException(status_code=503, detail="Service not ready")

        flows = await _tracker.get_flow_history(entity_id)

        result = {}
        for chain, flow_data in flows.items():
            result[chain] = {
                "total_inflow": flow_data.total_inflow,
                "total_outflow": flow_data.total_outflow,
                "net_flow": flow_data.net_flow,
                "data_points": [
                    {
                        "timestamp": dp.timestamp.isoformat(),
                        "inflow": dp.inflow,
                        "outflow": dp.outflow,
                        "cumulative_inflow": dp.cumulative_inflow,
                        "cumulative_outflow": dp.cumulative_outflow,
                    }
                    for dp in flow_data.data_points[-90:]  # Last 90 days
                ],
            }

        return {"entity_id": entity_id, "flows": result}

    @app.get("/api/v1/compare")
    async def compare_funds(funds: str):
        """Compare multiple funds. Pass comma-separated fund IDs."""
        if not _tracker:
            raise HTTPException(status_code=503, detail="Service not ready")

        fund_ids = [f.strip() for f in funds.split(",") if f.strip()]
        if not fund_ids:
            raise HTTPException(status_code=400, detail="No fund IDs provided")

        comparison = await _tracker.get_fund_comparison(fund_ids)
        return {"comparison": comparison}

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "cache_stats": _cache.stats() if _cache else {},
        }

    return app


# Create app instance
app = create_app()
