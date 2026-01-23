"""
Signal Generator

High-level signal generation combining sentiment strategy
with additional market data for improved signal quality.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from core.client import SantimentClient
from core.models import TradingSignal
from .strategy import SentimentStrategy, StrategyConfig, StrategyType


@dataclass
class SignalWithContext:
    """Trading signal with additional market context."""
    signal: TradingSignal
    asset_slug: str

    # Price context
    price_change_24h: float
    price_change_7d: float

    # Sentiment context
    sentiment_change_24h: float
    social_volume_change_24h: float

    # Divergence analysis
    price_sentiment_divergence: bool  # True if price and sentiment disagree
    divergence_direction: Optional[str]  # "bullish" or "bearish"

    # Confidence adjustments
    adjusted_strength: float
    confidence_factors: list[str]

    def to_dict(self) -> dict:
        return {
            "signal": {
                "type": self.signal.signal_type,
                "strength": self.signal.strength,
                "adjusted_strength": self.adjusted_strength,
                "reason": self.signal.reason,
                "price_at_signal": self.signal.price_at_signal,
                "stop_loss": self.signal.suggested_stop_loss,
                "take_profit": self.signal.suggested_take_profit,
            },
            "asset": self.asset_slug,
            "context": {
                "price_change_24h": self.price_change_24h,
                "price_change_7d": self.price_change_7d,
                "sentiment_change_24h": self.sentiment_change_24h,
                "social_volume_change_24h": self.social_volume_change_24h,
            },
            "divergence": {
                "detected": self.price_sentiment_divergence,
                "direction": self.divergence_direction,
            },
            "confidence_factors": self.confidence_factors,
            "generated_at": self.signal.datetime.isoformat(),
        }


class SignalGenerator:
    """
    High-level signal generator that combines sentiment analysis
    with price action and divergence detection.
    """

    def __init__(
        self,
        client: SantimentClient,
        config: Optional[StrategyConfig] = None,
    ):
        self.client = client
        self.strategy = SentimentStrategy(config)

    async def generate_signal(
        self,
        asset_slug: str,
        lookback_days: int = 14,
    ) -> Optional[SignalWithContext]:
        """
        Generate a trading signal with full market context.

        Args:
            asset_slug: Asset to analyze
            lookback_days: Days of historical data to analyze

        Returns:
            SignalWithContext if signal generated, None otherwise
        """
        now = datetime.utcnow()
        from_date = now - timedelta(days=lookback_days)

        # Fetch all required data in parallel
        sentiment_data, price_data, sentiment_24h_ago = await asyncio.gather(
            self.client.get_sentiment(asset_slug, from_date, now, "1d"),
            self.client.get_price(asset_slug, from_date, now, "1d"),
            self.client.get_sentiment(
                asset_slug,
                now - timedelta(days=2),
                now - timedelta(days=1),
                "1d"
            ),
            return_exceptions=True,
        )

        # Handle errors
        if isinstance(sentiment_data, Exception) or not sentiment_data:
            return None
        if isinstance(price_data, Exception) or not price_data:
            return None

        # Get current price
        current_price = price_data[-1].get("closePriceUsd", 0) if price_data else 0
        if current_price <= 0:
            return None

        # Generate base signal
        signal = self.strategy.generate_signal(asset_slug, sentiment_data, current_price)

        if not signal:
            return None

        # Calculate price changes
        price_24h_ago = price_data[-2].get("closePriceUsd", current_price) if len(price_data) > 1 else current_price
        price_7d_ago = price_data[-8].get("closePriceUsd", current_price) if len(price_data) > 7 else current_price

        price_change_24h = ((current_price - price_24h_ago) / price_24h_ago * 100) if price_24h_ago > 0 else 0
        price_change_7d = ((current_price - price_7d_ago) / price_7d_ago * 100) if price_7d_ago > 0 else 0

        # Calculate sentiment changes
        current_sentiment = sentiment_data[-1].sentiment_weighted
        sentiment_24h = sentiment_24h_ago[0].sentiment_weighted if sentiment_24h_ago and not isinstance(sentiment_24h_ago, Exception) else current_sentiment
        sentiment_change_24h = current_sentiment - sentiment_24h

        current_volume = sentiment_data[-1].social_volume
        volume_24h = sentiment_24h_ago[0].social_volume if sentiment_24h_ago and not isinstance(sentiment_24h_ago, Exception) else current_volume
        volume_change_24h = ((current_volume - volume_24h) / volume_24h * 100) if volume_24h > 0 else 0

        # Detect divergence
        divergence, divergence_dir = self._detect_divergence(
            price_change_7d, current_sentiment, sentiment_change_24h
        )

        # Calculate adjusted strength with confidence factors
        adjusted_strength, factors = self._calculate_adjusted_strength(
            signal, price_change_24h, price_change_7d,
            sentiment_change_24h, volume_change_24h, divergence, divergence_dir
        )

        return SignalWithContext(
            signal=signal,
            asset_slug=asset_slug,
            price_change_24h=round(price_change_24h, 2),
            price_change_7d=round(price_change_7d, 2),
            sentiment_change_24h=round(sentiment_change_24h, 2),
            social_volume_change_24h=round(volume_change_24h, 2),
            price_sentiment_divergence=divergence,
            divergence_direction=divergence_dir,
            adjusted_strength=round(adjusted_strength, 2),
            confidence_factors=factors,
        )

    def _detect_divergence(
        self,
        price_change_7d: float,
        sentiment: float,
        sentiment_change: float,
    ) -> tuple[bool, Optional[str]]:
        """
        Detect price-sentiment divergence.

        Divergence occurs when price and sentiment move in opposite directions.
        - Bullish divergence: Price falling but sentiment improving
        - Bearish divergence: Price rising but sentiment falling
        """
        # Price rising significantly but sentiment negative/falling
        if price_change_7d > 10 and (sentiment < -0.1 or sentiment_change < -0.2):
            return True, "bearish"

        # Price falling significantly but sentiment positive/improving
        if price_change_7d < -10 and (sentiment > 0.1 or sentiment_change > 0.2):
            return True, "bullish"

        return False, None

    def _calculate_adjusted_strength(
        self,
        signal: TradingSignal,
        price_change_24h: float,
        price_change_7d: float,
        sentiment_change: float,
        volume_change: float,
        divergence: bool,
        divergence_dir: Optional[str],
    ) -> tuple[float, list[str]]:
        """
        Adjust signal strength based on additional factors.

        Returns adjusted strength and list of confidence factors.
        """
        strength = signal.strength
        factors = []

        # Volume confirmation
        if volume_change > 50:
            strength *= 1.1
            factors.append(f"+10% Social volume spike ({volume_change:.0f}%)")
        elif volume_change < -30:
            strength *= 0.9
            factors.append(f"-10% Declining social volume ({volume_change:.0f}%)")

        # Divergence handling
        if divergence:
            if divergence_dir == "bullish" and signal.signal_type == "BUY":
                strength *= 1.2
                factors.append("+20% Bullish divergence confirms buy")
            elif divergence_dir == "bearish" and signal.signal_type == "SELL":
                strength *= 1.2
                factors.append("+20% Bearish divergence confirms sell")
            elif divergence_dir == "bullish" and signal.signal_type == "SELL":
                strength *= 0.7
                factors.append("-30% Bullish divergence conflicts with sell")
            elif divergence_dir == "bearish" and signal.signal_type == "BUY":
                strength *= 0.7
                factors.append("-30% Bearish divergence conflicts with buy")

        # Trend alignment
        if signal.signal_type == "BUY" and price_change_7d < -15:
            strength *= 1.1
            factors.append("+10% Price oversold (7d decline)")
        elif signal.signal_type == "SELL" and price_change_7d > 20:
            strength *= 1.1
            factors.append("+10% Price overbought (7d rally)")

        # Sentiment momentum
        if signal.signal_type == "BUY" and sentiment_change > 0.1:
            strength *= 1.05
            factors.append("+5% Sentiment improving")
        elif signal.signal_type == "SELL" and sentiment_change < -0.1:
            strength *= 1.05
            factors.append("+5% Sentiment deteriorating")

        # Cap strength at 1.0
        strength = min(1.0, strength)

        return strength, factors

    async def scan_multiple_assets(
        self,
        slugs: list[str],
        lookback_days: int = 14,
    ) -> list[SignalWithContext]:
        """
        Scan multiple assets for trading signals.

        Returns all assets with valid signals, sorted by strength.
        """
        results = await asyncio.gather(
            *[self.generate_signal(slug, lookback_days) for slug in slugs],
            return_exceptions=True,
        )

        signals = [r for r in results if isinstance(r, SignalWithContext)]
        signals.sort(key=lambda x: x.adjusted_strength, reverse=True)

        return signals

    async def get_actionable_signals(
        self,
        slugs: list[str],
        min_strength: float = 0.6,
        lookback_days: int = 14,
    ) -> list[SignalWithContext]:
        """
        Get only actionable signals (above minimum strength).
        """
        signals = await self.scan_multiple_assets(slugs, lookback_days)
        return [s for s in signals if s.adjusted_strength >= min_strength]

    def get_strategy_config(self) -> StrategyConfig:
        """Get current strategy configuration."""
        return self.strategy.config

    def update_strategy_config(self, config: StrategyConfig) -> None:
        """Update strategy configuration."""
        self.strategy = SentimentStrategy(config)
