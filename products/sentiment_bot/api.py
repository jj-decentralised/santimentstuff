"""
Sentiment Bot REST API

FastAPI-based REST API for sentiment trading signals and backtesting.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.client import SantimentClient
from core.cache import CacheManager
from .strategy import StrategyConfig, StrategyType
from .signals import SignalGenerator
from .backtest import Backtester


# ==================== Pydantic Models ====================

class StrategyConfigRequest(BaseModel):
    """Request model for strategy configuration."""
    strategy_type: str = Field(default="contrarian")
    buy_threshold: float = Field(default=-0.3, ge=-1, le=0)
    sell_threshold: float = Field(default=0.5, ge=0, le=1)
    extreme_buy_threshold: float = Field(default=-0.5, ge=-1, le=0)
    extreme_sell_threshold: float = Field(default=0.7, ge=0, le=1)
    min_social_volume: int = Field(default=100, ge=0)
    stop_loss_percent: float = Field(default=5.0, ge=1, le=50)
    take_profit_percent: float = Field(default=15.0, ge=1, le=100)
    signal_cooldown_hours: int = Field(default=24, ge=1)


class SignalResponse(BaseModel):
    """Response model for trading signal."""
    asset: str
    signal_type: str
    strength: float
    adjusted_strength: float
    reason: str
    price_at_signal: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    context: dict
    divergence: dict
    confidence_factors: list[str]
    generated_at: datetime


class BacktestRequest(BaseModel):
    """Request model for backtest."""
    asset_slug: str
    start_date: datetime
    end_date: datetime
    strategy_config: Optional[StrategyConfigRequest] = None
    initial_capital: float = Field(default=10000.0, ge=100)


class BacktestResponse(BaseModel):
    """Response model for backtest results."""
    asset: str
    period: dict
    strategy: dict
    statistics: dict
    returns: dict
    risk: dict
    timing: dict
    trades: list[dict]


class OptimizeRequest(BaseModel):
    """Request model for parameter optimization."""
    asset_slug: str
    start_date: datetime
    end_date: datetime
    param_ranges: Optional[dict] = None


# ==================== Dependencies ====================

_client: Optional[SantimentClient] = None
_signal_generator: Optional[SignalGenerator] = None
_backtester: Optional[Backtester] = None


async def get_signal_generator() -> SignalGenerator:
    """Dependency to get the signal generator."""
    global _client, _signal_generator
    if _signal_generator is None:
        cache = CacheManager.create(use_redis=False)
        _client = SantimentClient(cache=cache)
        await _client.__aenter__()
        _signal_generator = SignalGenerator(_client)
    return _signal_generator


async def get_backtester() -> Backtester:
    """Dependency to get the backtester."""
    global _client, _backtester
    if _backtester is None:
        if _client is None:
            cache = CacheManager.create(use_redis=False)
            _client = SantimentClient(cache=cache)
            await _client.__aenter__()
        _backtester = Backtester(_client)
    return _backtester


# ==================== App Factory ====================

def create_sentiment_bot_app() -> FastAPI:
    """Create the FastAPI application for Sentiment Bot."""

    app = FastAPI(
        title="Sentiment Trading Bot API",
        description="""
        Automated trading signal generation based on social sentiment analysis.

        ## Strategy Types
        - **Contrarian**: Buy fear, sell greed (default)
        - **Momentum**: Follow the crowd sentiment
        - **Mean Reversion**: Bet on sentiment returning to average
        - **Hybrid**: Combines contrarian + mean reversion

        ## Signal Interpretation
        - **Strength 0.6-0.7**: Moderate signal, consider with other factors
        - **Strength 0.7-0.85**: Strong signal, actionable
        - **Strength 0.85+**: Extreme signal, high conviction

        ## Risk Management
        All signals include suggested stop-loss and take-profit levels
        based on the configured risk parameters.
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

    # ==================== Signal Endpoints ====================

    @app.get("/")
    async def root():
        """API root with service information."""
        return {
            "service": "Sentiment Trading Bot API",
            "version": "1.0.0",
            "endpoints": {
                "signal": "/signal/{slug}",
                "scan": "/scan",
                "backtest": "/backtest",
                "optimize": "/optimize",
                "strategy": "/strategy",
            }
        }

    @app.get("/signal/{slug}")
    async def get_signal(
        slug: str,
        lookback_days: int = Query(default=14, ge=7, le=90),
        generator: SignalGenerator = Depends(get_signal_generator),
    ):
        """
        Generate a trading signal for a single asset.

        Returns signal with full market context and confidence factors.
        """
        try:
            result = await generator.generate_signal(slug, lookback_days)

            if result is None:
                return {
                    "asset": slug,
                    "signal": None,
                    "reason": "No actionable signal at this time",
                    "analyzed_at": datetime.utcnow().isoformat(),
                }

            return result.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/scan")
    async def scan_assets(
        slugs: list[str],
        min_strength: float = Query(default=0.5, ge=0, le=1),
        lookback_days: int = Query(default=14, ge=7, le=90),
        generator: SignalGenerator = Depends(get_signal_generator),
    ):
        """
        Scan multiple assets for trading signals.

        Returns all assets with signals above minimum strength, sorted by strength.
        """
        if len(slugs) > 50:
            raise HTTPException(status_code=400, detail="Maximum 50 assets per scan")

        try:
            signals = await generator.get_actionable_signals(
                slugs, min_strength, lookback_days
            )

            return {
                "signals": [s.to_dict() for s in signals],
                "count": len(signals),
                "scanned": len(slugs),
                "min_strength": min_strength,
                "scanned_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/scan/top")
    async def scan_top_assets(
        min_strength: float = Query(default=0.6, ge=0, le=1),
        generator: SignalGenerator = Depends(get_signal_generator),
    ):
        """
        Scan top market cap assets for trading signals.

        Automatically scans major cryptocurrencies.
        """
        top_assets = [
            "bitcoin", "ethereum", "ripple", "cardano", "solana",
            "polkadot", "avalanche", "polygon", "chainlink", "uniswap",
            "litecoin", "cosmos", "algorand", "near-protocol", "fantom",
            "aave", "maker", "compound", "curve", "synthetix"
        ]

        try:
            signals = await generator.get_actionable_signals(
                top_assets, min_strength, lookback_days=14
            )

            return {
                "signals": [s.to_dict() for s in signals],
                "count": len(signals),
                "assets_scanned": top_assets,
                "min_strength": min_strength,
                "scanned_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== Strategy Endpoints ====================

    @app.get("/strategy")
    async def get_strategy_config(
        generator: SignalGenerator = Depends(get_signal_generator),
    ):
        """Get current strategy configuration."""
        config = generator.get_strategy_config()
        return {
            "strategy_type": config.strategy_type.value,
            "buy_threshold": config.buy_threshold,
            "sell_threshold": config.sell_threshold,
            "extreme_buy_threshold": config.extreme_buy_threshold,
            "extreme_sell_threshold": config.extreme_sell_threshold,
            "min_social_volume": config.min_social_volume,
            "stop_loss_percent": config.stop_loss_percent,
            "take_profit_percent": config.take_profit_percent,
            "signal_cooldown_hours": config.signal_cooldown_hours,
        }

    @app.post("/strategy")
    async def update_strategy_config(
        config: StrategyConfigRequest,
        generator: SignalGenerator = Depends(get_signal_generator),
    ):
        """Update strategy configuration."""
        try:
            strategy_type = StrategyType(config.strategy_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid strategy type: {config.strategy_type}"
            )

        new_config = StrategyConfig(
            strategy_type=strategy_type,
            buy_threshold=config.buy_threshold,
            sell_threshold=config.sell_threshold,
            extreme_buy_threshold=config.extreme_buy_threshold,
            extreme_sell_threshold=config.extreme_sell_threshold,
            min_social_volume=config.min_social_volume,
            stop_loss_percent=config.stop_loss_percent,
            take_profit_percent=config.take_profit_percent,
            signal_cooldown_hours=config.signal_cooldown_hours,
        )

        generator.update_strategy_config(new_config)

        return {
            "status": "updated",
            "config": config.model_dump(),
        }

    # ==================== Backtest Endpoints ====================

    @app.post("/backtest")
    async def run_backtest(
        request: BacktestRequest,
        backtester: Backtester = Depends(get_backtester),
    ):
        """
        Run a historical backtest.

        Simulates trading based on historical sentiment data.
        """
        # Validate dates
        if request.end_date <= request.start_date:
            raise HTTPException(status_code=400, detail="end_date must be after start_date")

        if (request.end_date - request.start_date).days > 365:
            raise HTTPException(status_code=400, detail="Maximum backtest period is 365 days")

        # Build strategy config
        strategy_config = None
        if request.strategy_config:
            try:
                strategy_type = StrategyType(request.strategy_config.strategy_type)
            except ValueError:
                strategy_type = StrategyType.CONTRARIAN

            strategy_config = StrategyConfig(
                strategy_type=strategy_type,
                buy_threshold=request.strategy_config.buy_threshold,
                sell_threshold=request.strategy_config.sell_threshold,
                extreme_buy_threshold=request.strategy_config.extreme_buy_threshold,
                extreme_sell_threshold=request.strategy_config.extreme_sell_threshold,
                min_social_volume=request.strategy_config.min_social_volume,
                stop_loss_percent=request.strategy_config.stop_loss_percent,
                take_profit_percent=request.strategy_config.take_profit_percent,
                signal_cooldown_hours=request.strategy_config.signal_cooldown_hours,
            )

        try:
            backtester.initial_capital = request.initial_capital
            result = await backtester.run_backtest(
                request.asset_slug,
                request.start_date,
                request.end_date,
                strategy_config,
            )

            return result.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/backtest/quick/{slug}")
    async def quick_backtest(
        slug: str,
        days: int = Query(default=90, ge=30, le=365),
        backtester: Backtester = Depends(get_backtester),
    ):
        """
        Run a quick backtest with default parameters.

        Uses last N days of data with default strategy.
        """
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        try:
            result = await backtester.run_backtest(slug, start_date, end_date)
            return result.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/optimize")
    async def optimize_parameters(
        request: OptimizeRequest,
        backtester: Backtester = Depends(get_backtester),
    ):
        """
        Optimize strategy parameters using grid search.

        Tests multiple parameter combinations and returns the best.
        """
        # Validate dates
        if request.end_date <= request.start_date:
            raise HTTPException(status_code=400, detail="end_date must be after start_date")

        if (request.end_date - request.start_date).days > 180:
            raise HTTPException(status_code=400, detail="Maximum optimization period is 180 days")

        try:
            result = await backtester.optimize_parameters(
                request.asset_slug,
                request.start_date,
                request.end_date,
                request.param_ranges,
            )

            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== Analysis Endpoints ====================

    @app.get("/sentiment/{slug}")
    async def get_sentiment_analysis(
        slug: str,
        days: int = Query(default=30, ge=7, le=90),
        generator: SignalGenerator = Depends(get_signal_generator),
    ):
        """
        Get detailed sentiment analysis for an asset.

        Returns historical sentiment with trend analysis.
        """
        try:
            now = datetime.utcnow()
            from_date = now - timedelta(days=days)

            sentiment_data = await generator.client.get_sentiment(
                slug, from_date, now, "1d"
            )

            if not sentiment_data:
                raise HTTPException(status_code=404, detail=f"No sentiment data for {slug}")

            # Calculate statistics
            sentiments = [s.sentiment_weighted for s in sentiment_data]
            volumes = [s.social_volume for s in sentiment_data]

            import numpy as np
            avg_sentiment = np.mean(sentiments)
            sentiment_std = np.std(sentiments)
            current_sentiment = sentiments[-1]
            sentiment_z_score = (current_sentiment - avg_sentiment) / sentiment_std if sentiment_std > 0 else 0

            # Trend (last 7 days vs previous)
            if len(sentiments) >= 14:
                recent_avg = np.mean(sentiments[-7:])
                prev_avg = np.mean(sentiments[-14:-7])
                trend = "improving" if recent_avg > prev_avg else "deteriorating"
            else:
                trend = "insufficient_data"

            return {
                "asset": slug,
                "period_days": days,
                "current": {
                    "sentiment": current_sentiment,
                    "social_volume": volumes[-1],
                    "level": sentiment_data[-1].sentiment_level.value,
                },
                "statistics": {
                    "mean": round(avg_sentiment, 3),
                    "std": round(sentiment_std, 3),
                    "z_score": round(sentiment_z_score, 2),
                    "min": round(min(sentiments), 3),
                    "max": round(max(sentiments), 3),
                },
                "trend": trend,
                "history": [
                    {
                        "date": s.datetime.isoformat(),
                        "sentiment": s.sentiment_weighted,
                        "volume": s.social_volume,
                    }
                    for s in sentiment_data
                ],
                "analyzed_at": now.isoformat(),
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/divergence/{slug}")
    async def check_divergence(
        slug: str,
        generator: SignalGenerator = Depends(get_signal_generator),
    ):
        """
        Check for price-sentiment divergence.

        Divergence often signals upcoming price reversals.
        """
        try:
            signal = await generator.generate_signal(slug, lookback_days=14)

            if signal is None:
                return {
                    "asset": slug,
                    "divergence_detected": False,
                    "message": "Insufficient data or no divergence",
                }

            return {
                "asset": slug,
                "divergence_detected": signal.price_sentiment_divergence,
                "direction": signal.divergence_direction,
                "price_change_7d": signal.price_change_7d,
                "sentiment_change_24h": signal.sentiment_change_24h,
                "interpretation": self._interpret_divergence(
                    signal.price_sentiment_divergence,
                    signal.divergence_direction,
                    signal.price_change_7d,
                ),
                "analyzed_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def _interpret_divergence(
        self,
        divergence: bool,
        direction: Optional[str],
        price_change: float,
    ) -> str:
        """Generate human-readable divergence interpretation."""
        if not divergence:
            return "No significant divergence detected. Price and sentiment are aligned."

        if direction == "bullish":
            return (
                f"Bullish divergence: Price has fallen {abs(price_change):.1f}% "
                "but sentiment is improving. This historically precedes price rebounds."
            )
        elif direction == "bearish":
            return (
                f"Bearish divergence: Price has risen {price_change:.1f}% "
                "but sentiment is weakening. This may signal an upcoming correction."
            )
        return "Divergence detected but direction unclear."

    @app.on_event("shutdown")
    async def shutdown():
        """Cleanup on shutdown."""
        global _client
        if _client:
            await _client.__aexit__(None, None, None)

    return app


# Create default app instance
app = create_sentiment_bot_app()
