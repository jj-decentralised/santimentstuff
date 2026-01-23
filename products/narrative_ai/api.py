"""
Narrative AI REST API

FastAPI-based REST API for market narrative generation using Santiment data.
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.client import SantimentClient
from core.cache import CacheManager
from .analyzer import NarrativeAnalyzer


# ==================== Pydantic Models ====================

class NarrativeResponse(BaseModel):
    """Response model for market narrative."""
    asset: str
    narrative: str
    key_drivers: list[str]
    sentiment_alignment: bool
    confidence_score: float
    context: dict
    generated_at: datetime


class DivergenceResponse(BaseModel):
    """Response model for divergence analysis."""
    asset: str
    has_divergence: bool
    divergence_type: Optional[str]
    price_change_7d: float
    sentiment: float
    analysis: str
    generated_at: datetime


class TrendingSummaryResponse(BaseModel):
    """Response model for trending summary."""
    trending_words: list[dict]
    associated_assets: list[str]
    summary: str
    generated_at: datetime


class WhaleSummaryResponse(BaseModel):
    """Response model for whale summary."""
    asset: str
    flow_signal: str
    net_flow: float
    holder_behavior: str
    summary: str
    generated_at: datetime


# ==================== Dependencies ====================

_client: Optional[SantimentClient] = None
_analyzer: Optional[NarrativeAnalyzer] = None


async def get_analyzer() -> NarrativeAnalyzer:
    """Dependency to get the narrative analyzer."""
    global _client, _analyzer
    if _analyzer is None:
        cache = CacheManager.create(use_redis=False)
        _client = SantimentClient(cache=cache)
        await _client.__aenter__()
        _analyzer = NarrativeAnalyzer(_client)
    return _analyzer


# ==================== App Factory ====================

def create_narrative_app() -> FastAPI:
    """Create the FastAPI application for Narrative AI."""

    app = FastAPI(
        title="Market Narrative Analyzer",
        description="""
        Market narrative generation using Santiment on-chain and social data.

        ## Features
        - **Market Narratives**: Analysis explaining price movements
        - **Divergence Analysis**: Detect price-sentiment divergences
        - **Trending Summary**: What the crypto community is discussing
        - **Whale Analysis**: Interpretation of whale activity

        All narratives are generated using intelligent templates
        powered by real-time Santiment data.
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

    # ==================== Endpoints ====================

    @app.get("/")
    async def root():
        """API root with service information."""
        return {
            "service": "Market Narrative Analyzer",
            "version": "1.0.0",
            "endpoints": {
                "narrative": "/narrative/{slug}",
                "divergence": "/divergence/{slug}",
                "trending": "/trending",
                "whale_analysis": "/whale/{slug}",
            }
        }

    @app.get("/narrative/{slug}", response_model=NarrativeResponse)
    async def get_narrative(
        slug: str,
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """
        Generate a market narrative for an asset.

        Combines price action, sentiment, whale activity, and trending topics
        into a coherent narrative explaining current market conditions.
        """
        try:
            insight = await analyzer.generate_narrative(slug)

            return NarrativeResponse(
                asset=slug,
                narrative=insight.narrative,
                key_drivers=insight.key_drivers,
                sentiment_alignment=insight.sentiment_alignment,
                confidence_score=insight.confidence_score,
                context={
                    "price_change_24h": insight.price_change_24h,
                    "social_volume_change": insight.social_volume_change,
                    "whale_activity": insight.whale_activity_summary,
                    "trending_topics": [w.word for w in insight.trending_topics],
                },
                generated_at=insight.datetime,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/divergence/{slug}", response_model=DivergenceResponse)
    async def get_divergence_analysis(
        slug: str,
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """
        Analyze price-sentiment divergence for an asset.

        Divergences often signal upcoming trend reversals:
        - Bullish divergence: Price falling but sentiment improving
        - Bearish divergence: Price rising but sentiment falling
        """
        try:
            result = await analyzer.generate_divergence_analysis(slug)

            return DivergenceResponse(
                asset=result["asset"],
                has_divergence=result["has_divergence"],
                divergence_type=result["divergence_type"],
                price_change_7d=result["price_change_7d"],
                sentiment=result["sentiment"],
                analysis=result["analysis"],
                generated_at=datetime.fromisoformat(result["generated_at"]),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/trending", response_model=TrendingSummaryResponse)
    async def get_trending_summary(
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """
        Get summary of trending topics in crypto social media.

        Analyzes what the community is discussing and potential market impact.
        """
        try:
            result = await analyzer.generate_trending_summary()

            return TrendingSummaryResponse(
                trending_words=result["trending_words"],
                associated_assets=result["associated_assets"],
                summary=result["summary"],
                generated_at=datetime.fromisoformat(result["generated_at"]),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/whale/{slug}", response_model=WhaleSummaryResponse)
    async def get_whale_analysis(
        slug: str,
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """
        Get analysis of whale activity.

        Interprets exchange flows and top holder behavior.
        """
        try:
            result = await analyzer.generate_whale_summary(slug)

            return WhaleSummaryResponse(
                asset=result["asset"],
                flow_signal=result["flow_signal"],
                net_flow=result["net_flow"],
                holder_behavior=result["holder_behavior"],
                summary=result["summary"],
                generated_at=datetime.fromisoformat(result["generated_at"]),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== Multi-Asset Endpoints ====================

    @app.post("/narrative/batch")
    async def get_batch_narratives(
        slugs: list[str],
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """
        Generate narratives for multiple assets.

        Maximum 10 assets per request.
        """
        if len(slugs) > 10:
            raise HTTPException(
                status_code=400,
                detail="Maximum 10 assets per batch request"
            )

        import asyncio
        results = await asyncio.gather(
            *[analyzer.generate_narrative(slug) for slug in slugs],
            return_exceptions=True,
        )

        narratives = []
        for slug, result in zip(slugs, results):
            if isinstance(result, Exception):
                narratives.append({
                    "asset": slug,
                    "error": str(result),
                })
            else:
                narratives.append({
                    "asset": slug,
                    "narrative": result.narrative,
                    "key_drivers": result.key_drivers,
                    "confidence": result.confidence_score,
                })

        return {
            "narratives": narratives,
            "count": len(narratives),
            "generated_at": datetime.utcnow().isoformat(),
        }

    @app.get("/market/summary")
    async def get_market_summary(
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """
        Get a comprehensive market summary.

        Combines trending topics with top asset narratives.
        """
        try:
            # Get trending summary
            trending = await analyzer.generate_trending_summary()

            # Get narratives for top assets
            top_assets = ["bitcoin", "ethereum", "solana"]
            import asyncio
            narratives = await asyncio.gather(
                *[analyzer.generate_narrative(slug) for slug in top_assets],
                return_exceptions=True,
            )

            asset_summaries = []
            for slug, result in zip(top_assets, narratives):
                if not isinstance(result, Exception):
                    asset_summaries.append({
                        "asset": slug,
                        "key_drivers": result.key_drivers,
                        "sentiment_aligned": result.sentiment_alignment,
                        "confidence": result.confidence_score,
                    })

            return {
                "market_overview": {
                    "trending_summary": trending["summary"],
                    "top_topics": [w["word"] for w in trending["trending_words"][:5]],
                },
                "top_assets": asset_summaries,
                "generated_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== Health Check ====================

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
        }

    @app.on_event("shutdown")
    async def shutdown():
        """Cleanup on shutdown."""
        global _client
        if _client:
            await _client.__aexit__(None, None, None)

    return app


# Create default app instance
app = create_narrative_app()
