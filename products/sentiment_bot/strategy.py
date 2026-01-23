"""
Sentiment Trading Strategy

Implements contrarian sentiment-based trading strategies:
- Buy when sentiment is extremely negative (crowd fear)
- Sell when sentiment is extremely positive (crowd euphoria)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import numpy as np

from core.models import SentimentData, TradingSignal


class StrategyType(Enum):
    """Types of sentiment strategies."""
    CONTRARIAN = "contrarian"  # Buy fear, sell greed
    MOMENTUM = "momentum"  # Follow the crowd
    MEAN_REVERSION = "mean_reversion"  # Bet on sentiment returning to mean
    HYBRID = "hybrid"  # Combines multiple approaches


@dataclass
class StrategyConfig:
    """Configuration for sentiment trading strategy."""

    # Strategy type
    strategy_type: StrategyType = StrategyType.CONTRARIAN

    # Sentiment thresholds for signals
    buy_threshold: float = -0.3  # Buy when sentiment below this
    sell_threshold: float = 0.5  # Sell when sentiment above this

    # Extreme thresholds for stronger signals
    extreme_buy_threshold: float = -0.5
    extreme_sell_threshold: float = 0.7

    # Social volume requirements
    min_social_volume: int = 100  # Minimum mentions for valid signal
    volume_spike_multiplier: float = 2.0  # Volume spike detection

    # Signal confirmation
    confirmation_periods: int = 2  # Consecutive periods to confirm signal
    lookback_periods: int = 14  # Periods for calculating averages

    # Risk management
    max_position_size: float = 0.1  # Max 10% of portfolio per trade
    stop_loss_percent: float = 5.0  # 5% stop loss
    take_profit_percent: float = 15.0  # 15% take profit

    # Cooldown
    signal_cooldown_hours: int = 24  # Hours between signals for same asset


@dataclass
class StrategyState:
    """Tracks state for a running strategy."""
    asset_slug: str
    last_signal_time: Optional[datetime] = None
    last_signal_type: Optional[str] = None
    current_position: float = 0.0  # Position size
    entry_price: Optional[float] = None
    sentiment_history: list[float] = field(default_factory=list)
    volume_history: list[int] = field(default_factory=list)


class SentimentStrategy:
    """
    Sentiment-based trading strategy engine.

    Generates trading signals based on social sentiment analysis
    using configurable contrarian or momentum approaches.
    """

    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()
        self._states: dict[str, StrategyState] = {}

    def get_state(self, asset_slug: str) -> StrategyState:
        """Get or create state for an asset."""
        if asset_slug not in self._states:
            self._states[asset_slug] = StrategyState(asset_slug=asset_slug)
        return self._states[asset_slug]

    def update_state(
        self,
        asset_slug: str,
        sentiment: SentimentData,
    ) -> None:
        """Update strategy state with new sentiment data."""
        state = self.get_state(asset_slug)

        # Update histories
        state.sentiment_history.append(sentiment.sentiment_weighted)
        state.volume_history.append(sentiment.social_volume)

        # Keep history bounded
        max_history = self.config.lookback_periods * 2
        if len(state.sentiment_history) > max_history:
            state.sentiment_history = state.sentiment_history[-max_history:]
            state.volume_history = state.volume_history[-max_history:]

    def generate_signal(
        self,
        asset_slug: str,
        sentiment_data: list[SentimentData],
        current_price: float,
    ) -> Optional[TradingSignal]:
        """
        Generate a trading signal based on sentiment data.

        Args:
            asset_slug: Asset to analyze
            sentiment_data: Recent sentiment data points
            current_price: Current asset price

        Returns:
            TradingSignal if conditions met, None otherwise
        """
        if not sentiment_data:
            return None

        state = self.get_state(asset_slug)

        # Update state with all new data
        for data in sentiment_data:
            self.update_state(asset_slug, data)

        # Check cooldown
        if state.last_signal_time:
            cooldown = timedelta(hours=self.config.signal_cooldown_hours)
            if datetime.utcnow() - state.last_signal_time < cooldown:
                return None

        # Get latest sentiment
        latest = sentiment_data[-1]

        # Check minimum volume requirement
        if latest.social_volume < self.config.min_social_volume:
            return None

        # Generate signal based on strategy type
        if self.config.strategy_type == StrategyType.CONTRARIAN:
            return self._contrarian_signal(state, latest, current_price)
        elif self.config.strategy_type == StrategyType.MOMENTUM:
            return self._momentum_signal(state, latest, current_price)
        elif self.config.strategy_type == StrategyType.MEAN_REVERSION:
            return self._mean_reversion_signal(state, latest, current_price)
        else:
            return self._hybrid_signal(state, latest, current_price)

    def _contrarian_signal(
        self,
        state: StrategyState,
        latest: SentimentData,
        current_price: float,
    ) -> Optional[TradingSignal]:
        """
        Contrarian strategy: Buy fear, sell greed.

        Psychology: When everyone is fearful, prices are often oversold.
        When everyone is greedy, prices are often overbought.
        """
        sentiment = latest.sentiment_weighted

        # Check for volume spike (indicates stronger signal)
        avg_volume = np.mean(state.volume_history) if state.volume_history else latest.social_volume
        is_volume_spike = latest.social_volume > avg_volume * self.config.volume_spike_multiplier

        # BUY signal: Extreme fear
        if sentiment <= self.config.extreme_buy_threshold:
            strength = min(1.0, abs(sentiment) / abs(self.config.extreme_buy_threshold))
            if is_volume_spike:
                strength = min(1.0, strength * 1.2)

            return self._create_signal(
                state=state,
                signal_type="BUY",
                strength=strength,
                reason=f"Extreme fear detected (sentiment: {sentiment:.2f}). "
                       f"Contrarian buy signal - crowd is panicking.",
                sentiment=sentiment,
                social_volume=latest.social_volume,
                current_price=current_price,
                is_extreme=True,
            )

        elif sentiment <= self.config.buy_threshold:
            # Confirm with consecutive periods
            if len(state.sentiment_history) >= self.config.confirmation_periods:
                recent = state.sentiment_history[-self.config.confirmation_periods:]
                if all(s <= self.config.buy_threshold for s in recent):
                    strength = min(0.8, abs(sentiment) / abs(self.config.buy_threshold) * 0.8)

                    return self._create_signal(
                        state=state,
                        signal_type="BUY",
                        strength=strength,
                        reason=f"Sustained negative sentiment (sentiment: {sentiment:.2f}). "
                               f"Contrarian buy opportunity.",
                        sentiment=sentiment,
                        social_volume=latest.social_volume,
                        current_price=current_price,
                        is_extreme=False,
                    )

        # SELL signal: Extreme greed
        elif sentiment >= self.config.extreme_sell_threshold:
            strength = min(1.0, sentiment / self.config.extreme_sell_threshold)
            if is_volume_spike:
                strength = min(1.0, strength * 1.2)

            return self._create_signal(
                state=state,
                signal_type="SELL",
                strength=strength,
                reason=f"Extreme greed detected (sentiment: {sentiment:.2f}). "
                       f"Contrarian sell signal - crowd is euphoric.",
                sentiment=sentiment,
                social_volume=latest.social_volume,
                current_price=current_price,
                is_extreme=True,
            )

        elif sentiment >= self.config.sell_threshold:
            # Confirm with consecutive periods
            if len(state.sentiment_history) >= self.config.confirmation_periods:
                recent = state.sentiment_history[-self.config.confirmation_periods:]
                if all(s >= self.config.sell_threshold for s in recent):
                    strength = min(0.8, sentiment / self.config.sell_threshold * 0.8)

                    return self._create_signal(
                        state=state,
                        signal_type="SELL",
                        strength=strength,
                        reason=f"Sustained positive sentiment (sentiment: {sentiment:.2f}). "
                               f"Consider taking profits.",
                        sentiment=sentiment,
                        social_volume=latest.social_volume,
                        current_price=current_price,
                        is_extreme=False,
                    )

        return None

    def _momentum_signal(
        self,
        state: StrategyState,
        latest: SentimentData,
        current_price: float,
    ) -> Optional[TradingSignal]:
        """
        Momentum strategy: Follow the crowd.

        Buy when sentiment is turning positive, sell when turning negative.
        """
        if len(state.sentiment_history) < self.config.lookback_periods:
            return None

        recent = state.sentiment_history[-self.config.lookback_periods:]
        sentiment = latest.sentiment_weighted
        avg_sentiment = np.mean(recent)
        sentiment_momentum = sentiment - avg_sentiment

        # BUY: Sentiment improving significantly
        if sentiment_momentum > 0.3 and sentiment > 0:
            strength = min(0.9, sentiment_momentum / 0.5)

            return self._create_signal(
                state=state,
                signal_type="BUY",
                strength=strength,
                reason=f"Sentiment momentum positive ({sentiment_momentum:.2f}). "
                       f"Crowd sentiment improving.",
                sentiment=sentiment,
                social_volume=latest.social_volume,
                current_price=current_price,
                is_extreme=False,
            )

        # SELL: Sentiment deteriorating
        elif sentiment_momentum < -0.3 and sentiment < 0:
            strength = min(0.9, abs(sentiment_momentum) / 0.5)

            return self._create_signal(
                state=state,
                signal_type="SELL",
                strength=strength,
                reason=f"Sentiment momentum negative ({sentiment_momentum:.2f}). "
                       f"Crowd sentiment deteriorating.",
                sentiment=sentiment,
                social_volume=latest.social_volume,
                current_price=current_price,
                is_extreme=False,
            )

        return None

    def _mean_reversion_signal(
        self,
        state: StrategyState,
        latest: SentimentData,
        current_price: float,
    ) -> Optional[TradingSignal]:
        """
        Mean reversion strategy: Bet on sentiment returning to average.

        Trade when sentiment deviates significantly from historical mean.
        """
        if len(state.sentiment_history) < self.config.lookback_periods:
            return None

        sentiment = latest.sentiment_weighted
        history = state.sentiment_history[-self.config.lookback_periods:]
        mean = np.mean(history)
        std = np.std(history) or 0.1

        z_score = (sentiment - mean) / std

        # BUY: Sentiment significantly below mean
        if z_score < -2.0:
            strength = min(1.0, abs(z_score) / 3.0)

            return self._create_signal(
                state=state,
                signal_type="BUY",
                strength=strength,
                reason=f"Sentiment {abs(z_score):.1f} std below mean. "
                       f"Mean reversion expected.",
                sentiment=sentiment,
                social_volume=latest.social_volume,
                current_price=current_price,
                is_extreme=abs(z_score) > 2.5,
            )

        # SELL: Sentiment significantly above mean
        elif z_score > 2.0:
            strength = min(1.0, z_score / 3.0)

            return self._create_signal(
                state=state,
                signal_type="SELL",
                strength=strength,
                reason=f"Sentiment {z_score:.1f} std above mean. "
                       f"Mean reversion expected.",
                sentiment=sentiment,
                social_volume=latest.social_volume,
                current_price=current_price,
                is_extreme=z_score > 2.5,
            )

        return None

    def _hybrid_signal(
        self,
        state: StrategyState,
        latest: SentimentData,
        current_price: float,
    ) -> Optional[TradingSignal]:
        """
        Hybrid strategy: Combines contrarian and mean reversion.

        Only signals when both approaches agree.
        """
        contrarian = self._contrarian_signal(state, latest, current_price)
        mean_rev = self._mean_reversion_signal(state, latest, current_price)

        # Both must agree on direction
        if contrarian and mean_rev:
            if contrarian.signal_type == mean_rev.signal_type:
                # Combine strengths
                avg_strength = (contrarian.strength + mean_rev.strength) / 2
                combined_reason = f"{contrarian.reason} Additionally: {mean_rev.reason}"

                return self._create_signal(
                    state=state,
                    signal_type=contrarian.signal_type,
                    strength=min(1.0, avg_strength * 1.1),  # Bonus for agreement
                    reason=combined_reason,
                    sentiment=latest.sentiment_weighted,
                    social_volume=latest.social_volume,
                    current_price=current_price,
                    is_extreme=True,  # Strong confluence
                )

        return None

    def _create_signal(
        self,
        state: StrategyState,
        signal_type: str,
        strength: float,
        reason: str,
        sentiment: float,
        social_volume: int,
        current_price: float,
        is_extreme: bool,
    ) -> TradingSignal:
        """Create a trading signal with risk management levels."""

        # Calculate stop loss and take profit
        if signal_type == "BUY":
            stop_loss = current_price * (1 - self.config.stop_loss_percent / 100)
            take_profit = current_price * (1 + self.config.take_profit_percent / 100)
        else:
            stop_loss = current_price * (1 + self.config.stop_loss_percent / 100)
            take_profit = current_price * (1 - self.config.take_profit_percent / 100)

        # Update state
        state.last_signal_time = datetime.utcnow()
        state.last_signal_type = signal_type

        return TradingSignal(
            datetime=datetime.utcnow(),
            asset_slug=state.asset_slug,
            signal_type=signal_type,
            strength=round(strength, 2),
            reason=reason,
            sentiment_score=sentiment,
            social_volume=social_volume,
            price_at_signal=current_price,
            suggested_stop_loss=round(stop_loss, 2),
            suggested_take_profit=round(take_profit, 2),
        )

    def reset_state(self, asset_slug: str) -> None:
        """Reset state for an asset."""
        if asset_slug in self._states:
            del self._states[asset_slug]

    def get_all_states(self) -> dict[str, StrategyState]:
        """Get all strategy states."""
        return self._states.copy()
