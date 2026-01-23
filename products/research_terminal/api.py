"""
Research Terminal REST API

Unified API combining all analysis products into a single interface.
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.client import SantimentClient
from core.cache import CacheManager
from .terminal import ResearchTerminal
from .screener import AssetScreener, ScreenerConfig, ScreenerFilter, FilterOperator


# ==================== Pydantic Models ====================

class AssetReportResponse(BaseModel):
    """Response model for asset report."""
    asset: dict
    generated_at: datetime
    price: dict
    health: dict
    whale_activity: dict
    social: dict
    signal: Optional[dict]
    narrative: dict


class MarketOverviewResponse(BaseModel):
    """Response model for market overview."""
    generated_at: datetime
    movers: dict
    sentiment: dict
    whale_signals: dict
    trending: list[str]
    opportunities: dict


class ScreenerFilterRequest(BaseModel):
    """Request model for a single screener filter."""
    metric: str
    operator: str = Field(..., description="gt, lt, gte, lte, eq, neq, between, in")
    value: float
    value_max: Optional[float] = None


class ScreenRequest(BaseModel):
    """Request model for custom screening."""
    filters: list[ScreenerFilterRequest]
    sort_by: str = Field(default="market_cap")
    sort_desc: bool = Field(default=True)
    limit: int = Field(default=50, ge=1, le=100)
    min_market_cap: float = Field(default=10_000_000)


class CompareRequest(BaseModel):
    """Request model for asset comparison."""
    slugs: list[str] = Field(..., min_length=2, max_length=5)


# ==================== Dependencies ====================

_terminal: Optional[ResearchTerminal] = None


async def get_terminal() -> ResearchTerminal:
    """Dependency to get the research terminal."""
    global _terminal
    if _terminal is None:
        _terminal = ResearchTerminal()
        await _terminal.__aenter__()
    return _terminal


# ==================== App Factory ====================

def create_terminal_app() -> FastAPI:
    """Create the FastAPI application for Research Terminal."""

    app = FastAPI(
        title="Crypto Research Terminal API",
        description="""
        Unified research interface combining all Santiment-powered analysis tools.

        ## Features

        ### Asset Reports
        Comprehensive analysis combining health score, whale activity,
        sentiment, trading signals, and AI-generated narratives.

        ### Market Overview
        Market-wide view of movers, sentiment, whale signals, and opportunities.

        ### Asset Screener
        Filter assets by multiple criteria:
        - Valuation (MVRV, NVT)
        - On-chain activity (DAA, network growth)
        - Social metrics (sentiment, volume)
        - Development activity
        - Whale activity
        - Price performance

        ### Presets
        Quick screens for common strategies:
        - `undervalued`: MVRV < 1 with good development
        - `oversold`: Large price drop with improving sentiment
        - `whale_accumulation`: Net exchange outflows
        - `high_activity`: High DAA and network growth
        - `momentum`: Strong price and sentiment momentum

        ## Integration
        This API combines:
        - Health Score API
        - Whale Watch API
        - Sentiment Bot API
        - Narrative AI API
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ==================== Main Endpoints ====================

    @app.get("/")
    async def root():
        """API root with service information."""
        return {
            "service": "Crypto Research Terminal",
            "version": "1.0.0",
            "endpoints": {
                "report": "/report/{slug}",
                "overview": "/overview",
                "compare": "/compare",
                "screen": "/screen",
                "presets": "/screen/presets",
            },
            "sub_products": {
                "health_score": "/health/{slug}",
                "whale_watch": "/whale/{slug}",
                "sentiment": "/sentiment/{slug}",
                "narrative": "/narrative/{slug}",
            }
        }

    @app.get("/report/{slug}")
    async def get_asset_report(
        slug: str,
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """
        Get comprehensive report for an asset.

        Combines all analysis products into a single unified report.
        """
        try:
            report = await terminal.get_asset_report(slug)
            return report.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/overview")
    async def get_market_overview(
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """
        Get market-wide overview.

        Includes top movers, sentiment, whale signals, and opportunities.
        """
        try:
            overview = await terminal.get_market_overview()
            return overview.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/compare")
    async def compare_assets(
        request: CompareRequest,
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """
        Compare multiple assets side-by-side.

        Maximum 5 assets per comparison.
        """
        try:
            comparison = await terminal.compare_assets(request.slugs)
            return comparison
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== Screener Endpoints ====================

    @app.get("/screen/presets")
    async def get_screener_presets():
        """Get available screening presets."""
        return {
            "presets": AssetScreener.get_available_presets(),
            "metrics": AssetScreener.get_available_metrics(),
        }

    @app.get("/screen/preset/{preset}")
    async def screen_preset(
        preset: str,
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """
        Run a screening preset.

        Available presets: undervalued, oversold, whale_accumulation,
        high_activity, momentum
        """
        try:
            results = await terminal.screen_assets(preset=preset)
            return {
                "preset": preset,
                "results": results,
                "count": len(results),
                "screened_at": datetime.utcnow().isoformat(),
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/screen")
    async def screen_custom(
        request: ScreenRequest,
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """
        Run custom screening with specified filters.

        Example filters:
        - {"metric": "mvrv", "operator": "lt", "value": 1.0}
        - {"metric": "sentiment", "operator": "gt", "value": 0.3}
        - {"metric": "dev_activity", "operator": "gte", "value": 50}
        """
        try:
            custom_filters = [
                {
                    "metric": f.metric,
                    "operator": f.operator,
                    "value": f.value,
                    "value_max": f.value_max,
                }
                for f in request.filters
            ]

            results = await terminal.screen_assets(custom_filters=custom_filters)
            return {
                "filters": [f.model_dump() for f in request.filters],
                "results": results[:request.limit],
                "count": len(results),
                "screened_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== Sub-Product Endpoints ====================

    @app.get("/health/{slug}")
    async def get_health_score(
        slug: str,
        lookback_days: int = Query(default=30, ge=7, le=90),
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """Get health score for an asset."""
        try:
            score = await terminal.health_calculator.calculate(slug, lookback_days)
            return {
                "asset": slug,
                "overall_score": score.overall_score,
                "grade": score.grade,
                "components": {
                    "development": score.dev_activity_score,
                    "distribution": score.holder_distribution_score,
                    "social": score.social_momentum_score,
                    "usage": score.onchain_usage_score,
                    "valuation": score.valuation_score,
                },
                "metrics": {
                    "dev_trend": score.dev_activity_trend,
                    "whale_concentration": score.whale_concentration,
                    "social_change": score.social_volume_change,
                    "daa_change": score.daa_change,
                    "mvrv": score.mvrv_position,
                },
                "flags": {
                    "red": score.red_flags,
                    "green": score.green_flags,
                },
                "computed_at": score.computed_at.isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/whale/{slug}")
    async def get_whale_dashboard(
        slug: str,
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """Get whale activity dashboard for an asset."""
        try:
            dashboard = await terminal.whale_tracker.get_whale_dashboard(slug)
            return dashboard
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/sentiment/{slug}")
    async def get_sentiment_signal(
        slug: str,
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """Get sentiment analysis and trading signal for an asset."""
        try:
            signal = await terminal.signal_generator.generate_signal(slug)
            if signal:
                return signal.to_dict()
            return {
                "asset": slug,
                "signal": None,
                "reason": "No actionable signal at this time",
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/narrative/{slug}")
    async def get_narrative(
        slug: str,
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """Get AI-generated market narrative for an asset."""
        try:
            narrative = await terminal.narrative_analyzer.generate_narrative(slug)
            return {
                "asset": slug,
                "narrative": narrative.narrative,
                "key_drivers": narrative.key_drivers,
                "sentiment_aligned": narrative.sentiment_alignment,
                "confidence": narrative.confidence_score,
                "generated_at": narrative.datetime.isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== Batch Endpoints ====================

    @app.post("/report/batch")
    async def get_batch_reports(
        slugs: list[str],
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """
        Get reports for multiple assets.

        Maximum 10 assets per request.
        """
        if len(slugs) > 10:
            raise HTTPException(status_code=400, detail="Maximum 10 assets per request")

        import asyncio
        results = await asyncio.gather(
            *[terminal.get_asset_report(slug) for slug in slugs],
            return_exceptions=True,
        )

        reports = []
        for slug, result in zip(slugs, results):
            if isinstance(result, Exception):
                reports.append({"asset": slug, "error": str(result)})
            else:
                reports.append(result.to_dict())

        return {
            "reports": reports,
            "count": len(reports),
            "generated_at": datetime.utcnow().isoformat(),
        }

    @app.get("/health/batch")
    async def get_batch_health_scores(
        slugs: str = Query(..., description="Comma-separated asset slugs"),
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """Get health scores for multiple assets."""
        slug_list = [s.strip() for s in slugs.split(",")][:20]

        try:
            scores = await terminal.health_calculator.calculate_batch(slug_list)
            return {
                "scores": [
                    {
                        "asset": s.asset_slug,
                        "score": s.overall_score,
                        "grade": s.grade,
                    }
                    for s in scores
                ],
                "count": len(scores),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== Watchlist Endpoints ====================

    @app.get("/watchlist/{slugs}")
    async def get_watchlist(
        slugs: str,
        terminal: ResearchTerminal = Depends(get_terminal),
    ):
        """
        Get quick overview for a watchlist of assets.

        Comma-separated slugs (max 20).
        """
        slug_list = [s.strip() for s in slugs.split(",")][:20]

        import asyncio
        now = datetime.utcnow()

        # Get basic data for all assets
        tasks = []
        for slug in slug_list:
            tasks.append(terminal._client.get_price(
                slug,
                now - __import__('datetime').timedelta(days=1),
                now,
                "1d"
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        watchlist = []
        for slug, price_data in zip(slug_list, results):
            if isinstance(price_data, Exception) or not price_data:
                watchlist.append({"asset": slug, "error": "No data"})
                continue

            current = price_data[-1].get("closePriceUsd", 0)
            prev = price_data[0].get("closePriceUsd", current)
            change = ((current - prev) / prev * 100) if prev else 0

            watchlist.append({
                "asset": slug,
                "price": current,
                "change_24h": round(change, 2),
            })

        return {
            "watchlist": watchlist,
            "count": len(watchlist),
            "updated_at": now.isoformat(),
        }

    # ==================== Health Check ====================

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "research-terminal",
            "timestamp": datetime.utcnow().isoformat(),
        }

    @app.on_event("shutdown")
    async def shutdown():
        """Cleanup on shutdown."""
        global _terminal
        if _terminal:
            await _terminal.__aexit__(None, None, None)

    return app


# Create default app instance
app = create_terminal_app()
