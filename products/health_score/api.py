"""
Health Score REST API

FastAPI-based REST API for the Project Health Score service.
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.client import SantimentClient
from core.cache import CacheManager
from .calculator import HealthScoreCalculator, ScoreWeights


# ==================== Pydantic Models ====================

class HealthScoreResponse(BaseModel):
    """Response model for health score endpoint."""
    asset_slug: str
    computed_at: datetime
    overall_score: float = Field(..., ge=0, le=100)
    grade: str

    # Component scores
    dev_activity_score: float = Field(..., ge=0, le=100)
    holder_distribution_score: float = Field(..., ge=0, le=100)
    social_momentum_score: float = Field(..., ge=0, le=100)
    onchain_usage_score: float = Field(..., ge=0, le=100)
    valuation_score: float = Field(..., ge=0, le=100)

    # Raw metrics
    dev_activity_trend: float
    whale_concentration: float
    social_volume_change: float
    daa_change: float
    mvrv_position: float

    # Flags
    red_flags: list[str]
    green_flags: list[str]

    class Config:
        json_schema_extra = {
            "example": {
                "asset_slug": "ethereum",
                "computed_at": "2024-01-15T10:30:00Z",
                "overall_score": 72.5,
                "grade": "B",
                "dev_activity_score": 85.0,
                "holder_distribution_score": 65.0,
                "social_momentum_score": 70.0,
                "onchain_usage_score": 75.0,
                "valuation_score": 67.5,
                "dev_activity_trend": 15.3,
                "whale_concentration": 28.5,
                "social_volume_change": 12.0,
                "daa_change": 8.5,
                "mvrv_position": 1.4,
                "red_flags": [],
                "green_flags": ["Strong development growth (15%)"]
            }
        }


class BatchHealthScoreRequest(BaseModel):
    """Request model for batch health score calculation."""
    slugs: list[str] = Field(..., min_length=1, max_length=50)
    lookback_days: int = Field(default=30, ge=7, le=90)


class BatchHealthScoreResponse(BaseModel):
    """Response model for batch health scores."""
    scores: list[HealthScoreResponse]
    computed_at: datetime
    count: int


class LeaderboardResponse(BaseModel):
    """Response model for health score leaderboard."""
    rankings: list[HealthScoreResponse]
    total_analyzed: int
    computed_at: datetime


class ComponentWeightsRequest(BaseModel):
    """Custom weights for health score calculation."""
    dev_activity: float = Field(default=0.20, ge=0, le=1)
    holder_distribution: float = Field(default=0.20, ge=0, le=1)
    social_momentum: float = Field(default=0.20, ge=0, le=1)
    onchain_usage: float = Field(default=0.20, ge=0, le=1)
    valuation: float = Field(default=0.20, ge=0, le=1)


# ==================== Dependencies ====================

_client: Optional[SantimentClient] = None
_calculator: Optional[HealthScoreCalculator] = None


async def get_calculator() -> HealthScoreCalculator:
    """Dependency to get the health score calculator."""
    global _client, _calculator
    if _calculator is None:
        cache = CacheManager.create(use_redis=False)
        _client = SantimentClient(cache=cache)
        await _client.__aenter__()
        _calculator = HealthScoreCalculator(_client)
    return _calculator


# ==================== App Factory ====================

def create_health_score_app() -> FastAPI:
    """Create the FastAPI application for Health Score API."""

    app = FastAPI(
        title="Project Health Score API",
        description="""
        Composite health scoring system for cryptocurrency projects.

        The Health Score combines five fundamental metrics into a single 0-100 score:
        - **Development Activity** (20%): GitHub commits, contributors, activity trend
        - **Holder Distribution** (20%): Decentralization, whale concentration
        - **Social Momentum** (20%): Social volume trend, sentiment direction
        - **On-chain Usage** (20%): DAA growth, transaction activity
        - **Valuation** (20%): MVRV position relative to historical norms

        ## Grading Scale
        - **A** (80-100): Excellent health across most metrics
        - **B** (60-79): Good health with minor concerns
        - **C** (40-59): Average health, notable weaknesses
        - **D** (20-39): Poor health, significant concerns
        - **F** (0-19): Critical issues, high risk
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
            "service": "Project Health Score API",
            "version": "1.0.0",
            "endpoints": {
                "health_score": "/score/{slug}",
                "batch": "/score/batch",
                "leaderboard": "/leaderboard",
                "compare": "/compare",
            }
        }

    @app.get("/score/{slug}", response_model=HealthScoreResponse)
    async def get_health_score(
        slug: str,
        lookback_days: int = Query(default=30, ge=7, le=90),
        calculator: HealthScoreCalculator = Depends(get_calculator),
    ):
        """
        Get the health score for a single asset.

        - **slug**: Asset identifier (e.g., "bitcoin", "ethereum", "cardano")
        - **lookback_days**: Number of days to analyze (default: 30)
        """
        try:
            score = await calculator.calculate(slug, lookback_days)
            return HealthScoreResponse(
                asset_slug=score.asset_slug,
                computed_at=score.computed_at,
                overall_score=score.overall_score,
                grade=score.grade,
                dev_activity_score=score.dev_activity_score,
                holder_distribution_score=score.holder_distribution_score,
                social_momentum_score=score.social_momentum_score,
                onchain_usage_score=score.onchain_usage_score,
                valuation_score=score.valuation_score,
                dev_activity_trend=score.dev_activity_trend,
                whale_concentration=score.whale_concentration,
                social_volume_change=score.social_volume_change,
                daa_change=score.daa_change,
                mvrv_position=score.mvrv_position,
                red_flags=score.red_flags,
                green_flags=score.green_flags,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/score/batch", response_model=BatchHealthScoreResponse)
    async def get_batch_health_scores(
        request: BatchHealthScoreRequest,
        calculator: HealthScoreCalculator = Depends(get_calculator),
    ):
        """
        Get health scores for multiple assets in a single request.

        Maximum 50 assets per request.
        """
        try:
            scores = await calculator.calculate_batch(
                request.slugs,
                request.lookback_days
            )

            responses = [
                HealthScoreResponse(
                    asset_slug=s.asset_slug,
                    computed_at=s.computed_at,
                    overall_score=s.overall_score,
                    grade=s.grade,
                    dev_activity_score=s.dev_activity_score,
                    holder_distribution_score=s.holder_distribution_score,
                    social_momentum_score=s.social_momentum_score,
                    onchain_usage_score=s.onchain_usage_score,
                    valuation_score=s.valuation_score,
                    dev_activity_trend=s.dev_activity_trend,
                    whale_concentration=s.whale_concentration,
                    social_volume_change=s.social_volume_change,
                    daa_change=s.daa_change,
                    mvrv_position=s.mvrv_position,
                    red_flags=s.red_flags,
                    green_flags=s.green_flags,
                )
                for s in scores
            ]

            return BatchHealthScoreResponse(
                scores=responses,
                computed_at=datetime.utcnow(),
                count=len(responses),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/leaderboard", response_model=LeaderboardResponse)
    async def get_leaderboard(
        top_n: int = Query(default=20, ge=1, le=100),
        min_market_cap: float = Query(default=100_000_000, ge=0),
        calculator: HealthScoreCalculator = Depends(get_calculator),
    ):
        """
        Get top assets ranked by health score.

        - **top_n**: Number of assets to return (default: 20)
        - **min_market_cap**: Minimum market cap filter in USD (default: 100M)
        """
        try:
            # Get all assets first
            assets = await calculator.client.get_all_assets()

            # Filter by market cap
            filtered_slugs = [
                a.slug for a in assets
                if a.market_cap_usd and a.market_cap_usd >= min_market_cap
            ][:100]  # Limit to top 100 by market cap for performance

            # Calculate scores
            scores = await calculator.get_top_by_health(filtered_slugs, top_n)

            responses = [
                HealthScoreResponse(
                    asset_slug=s.asset_slug,
                    computed_at=s.computed_at,
                    overall_score=s.overall_score,
                    grade=s.grade,
                    dev_activity_score=s.dev_activity_score,
                    holder_distribution_score=s.holder_distribution_score,
                    social_momentum_score=s.social_momentum_score,
                    onchain_usage_score=s.onchain_usage_score,
                    valuation_score=s.valuation_score,
                    dev_activity_trend=s.dev_activity_trend,
                    whale_concentration=s.whale_concentration,
                    social_volume_change=s.social_volume_change,
                    daa_change=s.daa_change,
                    mvrv_position=s.mvrv_position,
                    red_flags=s.red_flags,
                    green_flags=s.green_flags,
                )
                for s in scores
            ]

            return LeaderboardResponse(
                rankings=responses,
                total_analyzed=len(filtered_slugs),
                computed_at=datetime.utcnow(),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/compare")
    async def compare_assets(
        slugs: str = Query(..., description="Comma-separated asset slugs"),
        calculator: HealthScoreCalculator = Depends(get_calculator),
    ):
        """
        Compare health scores of multiple assets side-by-side.

        - **slugs**: Comma-separated list of asset slugs (max 5)
        """
        slug_list = [s.strip() for s in slugs.split(",")][:5]

        if len(slug_list) < 2:
            raise HTTPException(
                status_code=400,
                detail="At least 2 assets required for comparison"
            )

        try:
            scores = await calculator.calculate_batch(slug_list)

            return {
                "comparison": [
                    {
                        "slug": s.asset_slug,
                        "overall": s.overall_score,
                        "grade": s.grade,
                        "components": {
                            "development": s.dev_activity_score,
                            "distribution": s.holder_distribution_score,
                            "social": s.social_momentum_score,
                            "usage": s.onchain_usage_score,
                            "valuation": s.valuation_score,
                        },
                        "flags": {
                            "red": len(s.red_flags),
                            "green": len(s.green_flags),
                        }
                    }
                    for s in scores
                ],
                "winner": max(scores, key=lambda x: x.overall_score).asset_slug if scores else None,
                "computed_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/score/{slug}/custom")
    async def get_custom_weighted_score(
        slug: str,
        weights: ComponentWeightsRequest,
        lookback_days: int = Query(default=30, ge=7, le=90),
        calculator: HealthScoreCalculator = Depends(get_calculator),
    ):
        """
        Calculate health score with custom component weights.

        Weights must sum to 1.0.
        """
        # Validate weights sum to 1.0
        total = (
            weights.dev_activity +
            weights.holder_distribution +
            weights.social_momentum +
            weights.onchain_usage +
            weights.valuation
        )

        if abs(total - 1.0) > 0.01:
            raise HTTPException(
                status_code=400,
                detail=f"Weights must sum to 1.0, got {total}"
            )

        try:
            custom_weights = ScoreWeights(
                dev_activity=weights.dev_activity,
                holder_distribution=weights.holder_distribution,
                social_momentum=weights.social_momentum,
                onchain_usage=weights.onchain_usage,
                valuation=weights.valuation,
            )

            custom_calculator = HealthScoreCalculator(
                calculator.client,
                weights=custom_weights
            )

            score = await custom_calculator.calculate(slug, lookback_days)

            return {
                "slug": score.asset_slug,
                "overall_score": score.overall_score,
                "grade": score.grade,
                "weights_used": weights.model_dump(),
                "components": {
                    "development": score.dev_activity_score,
                    "distribution": score.holder_distribution_score,
                    "social": score.social_momentum_score,
                    "usage": score.onchain_usage_score,
                    "valuation": score.valuation_score,
                },
                "computed_at": score.computed_at.isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.on_event("shutdown")
    async def shutdown():
        """Cleanup on shutdown."""
        global _client
        if _client:
            await _client.__aexit__(None, None, None)

    return app


# Create default app instance
app = create_health_score_app()
