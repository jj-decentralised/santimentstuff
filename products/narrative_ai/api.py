"""
Narrative AI REST API

FastAPI-based REST API for AI-powered market narrative generation.
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.client import SantimentClient
from core.cache import CacheManager
from .analyzer import (
    NarrativeAnalyzer,
    OpenAIProvider,
    AnthropicProvider,
    MockProvider,
)


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


class LLMConfigRequest(BaseModel):
    """Request model for LLM configuration."""
    provider: str = Field(..., description="LLM provider: 'openai', 'anthropic', or 'mock'")
    api_key: Optional[str] = Field(None, description="API key (uses env var if not provided)")
    model: Optional[str] = Field(None, description="Model name (uses default if not provided)")


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
        _analyzer = NarrativeAnalyzer(_client, MockProvider())
    return _analyzer


# ==================== App Factory ====================

def create_narrative_app() -> FastAPI:
    """Create the FastAPI application for Narrative AI."""

    app = FastAPI(
        title="AI Market Narrative Analyzer",
        description="""
        LLM-powered market analysis that combines multiple data sources
        to generate human-readable market narratives.

        ## Features
        - **Market Narratives**: Full analysis explaining price movements
        - **Divergence Analysis**: Detect price-sentiment divergences
        - **Trending Summary**: What the crypto community is discussing
        - **Whale Analysis**: AI interpretation of whale activity

        ## LLM Providers
        Supports multiple LLM providers:
        - **OpenAI**: GPT-4 and GPT-3.5
        - **Anthropic**: Claude models
        - **Mock**: For testing without API costs

        Configure the provider using the `/config/llm` endpoint.
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
            "service": "AI Market Narrative Analyzer",
            "version": "1.0.0",
            "endpoints": {
                "narrative": "/narrative/{slug}",
                "divergence": "/divergence/{slug}",
                "trending": "/trending",
                "whale_analysis": "/whale/{slug}",
                "config": "/config/llm",
            }
        }

    @app.get("/narrative/{slug}", response_model=NarrativeResponse)
    async def get_narrative(
        slug: str,
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """
        Generate a full market narrative for an asset.

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
        Get AI-generated summary of trending topics in crypto social media.

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
        Get AI-generated analysis of whale activity.

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

        Maximum 5 assets per request (LLM cost consideration).
        """
        if len(slugs) > 5:
            raise HTTPException(
                status_code=400,
                detail="Maximum 5 assets per batch request"
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

    # ==================== Configuration Endpoints ====================

    @app.post("/config/llm")
    async def configure_llm(
        config: LLMConfigRequest,
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """
        Configure the LLM provider.

        Supported providers:
        - `openai`: Uses GPT-4 or specified model
        - `anthropic`: Uses Claude or specified model
        - `mock`: For testing (no API calls)
        """
        try:
            if config.provider == "openai":
                provider = OpenAIProvider(
                    api_key=config.api_key,
                    model=config.model or "gpt-4",
                )
            elif config.provider == "anthropic":
                provider = AnthropicProvider(
                    api_key=config.api_key,
                    model=config.model or "claude-3-sonnet-20240229",
                )
            elif config.provider == "mock":
                provider = MockProvider()
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown provider: {config.provider}"
                )

            analyzer.set_llm_provider(provider)

            return {
                "status": "configured",
                "provider": config.provider,
                "model": config.model,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/config/llm")
    async def get_llm_config(
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """Get current LLM configuration."""
        provider_name = type(analyzer.llm).__name__
        return {
            "provider": provider_name.replace("Provider", "").lower(),
            "note": "Use POST /config/llm to change provider",
        }

    # ==================== Health Check ====================

    @app.get("/health")
    async def health_check(
        analyzer: NarrativeAnalyzer = Depends(get_analyzer),
    ):
        """Health check endpoint."""
        return {
            "status": "healthy",
            "llm_provider": type(analyzer.llm).__name__,
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
