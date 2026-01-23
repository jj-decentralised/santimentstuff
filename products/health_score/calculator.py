"""
Health Score Calculator

Computes a composite health score (0-100) for cryptocurrency projects
based on multiple fundamental metrics.

Scoring Components:
1. Development Activity (20%): GitHub commits, contributors, activity trend
2. Holder Distribution (20%): Decentralization, whale concentration
3. Social Momentum (20%): Social volume trend, sentiment direction
4. On-chain Usage (20%): DAA growth, transaction activity
5. Valuation (20%): MVRV position relative to historical norms
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from core.client import SantimentClient
from core.models import HealthScore


@dataclass
class ScoreWeights:
    """Configurable weights for health score components."""
    dev_activity: float = 0.20
    holder_distribution: float = 0.20
    social_momentum: float = 0.20
    onchain_usage: float = 0.20
    valuation: float = 0.20

    def __post_init__(self):
        total = sum([
            self.dev_activity,
            self.holder_distribution,
            self.social_momentum,
            self.onchain_usage,
            self.valuation
        ])
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


class HealthScoreCalculator:
    """
    Calculates comprehensive health scores for cryptocurrency projects.

    The score combines five fundamental components, each scored 0-100,
    then weighted to produce an overall score.
    """

    def __init__(
        self,
        client: SantimentClient,
        weights: Optional[ScoreWeights] = None,
    ):
        self.client = client
        self.weights = weights or ScoreWeights()

    async def calculate(
        self,
        slug: str,
        lookback_days: int = 30,
    ) -> HealthScore:
        """
        Calculate the health score for an asset.

        Args:
            slug: Asset slug (e.g., "bitcoin", "ethereum")
            lookback_days: Number of days to analyze for trends

        Returns:
            HealthScore with component scores and flags
        """
        now = datetime.utcnow()
        from_date = now - timedelta(days=lookback_days)
        comparison_from = now - timedelta(days=lookback_days * 2)

        # Fetch all required data in parallel
        (
            dev_activity,
            sentiment,
            valuation,
            network,
            top_holders,
            dev_activity_prev,
            sentiment_prev,
            network_prev,
        ) = await asyncio.gather(
            self.client.get_dev_activity(slug, from_date, now),
            self.client.get_sentiment(slug, from_date, now),
            self.client.get_valuation_metrics(slug, from_date, now),
            self.client.get_network_metrics(slug, from_date, now),
            self.client.get_top_holders(slug, 100),
            self.client.get_dev_activity(slug, comparison_from, from_date),
            self.client.get_sentiment(slug, comparison_from, from_date),
            self.client.get_network_metrics(slug, comparison_from, from_date),
            return_exceptions=True,
        )

        # Calculate component scores
        dev_score, dev_trend = self._calculate_dev_score(dev_activity, dev_activity_prev)
        holder_score, whale_concentration = self._calculate_holder_score(top_holders)
        social_score, social_change = self._calculate_social_score(sentiment, sentiment_prev)
        usage_score, daa_change = self._calculate_usage_score(network, network_prev)
        val_score, mvrv_position = self._calculate_valuation_score(valuation)

        # Calculate weighted overall score
        overall_score = (
            dev_score * self.weights.dev_activity +
            holder_score * self.weights.holder_distribution +
            social_score * self.weights.social_momentum +
            usage_score * self.weights.onchain_usage +
            val_score * self.weights.valuation
        )

        # Generate flags
        red_flags = self._generate_red_flags(
            dev_trend, whale_concentration, social_change, daa_change, mvrv_position
        )
        green_flags = self._generate_green_flags(
            dev_trend, whale_concentration, social_change, daa_change, mvrv_position
        )

        return HealthScore(
            asset_slug=slug,
            computed_at=now,
            overall_score=round(overall_score, 1),
            dev_activity_score=round(dev_score, 1),
            holder_distribution_score=round(holder_score, 1),
            social_momentum_score=round(social_score, 1),
            onchain_usage_score=round(usage_score, 1),
            valuation_score=round(val_score, 1),
            dev_activity_trend=round(dev_trend, 2),
            whale_concentration=round(whale_concentration, 2),
            social_volume_change=round(social_change, 2),
            daa_change=round(daa_change, 2),
            mvrv_position=round(mvrv_position, 2),
            red_flags=red_flags,
            green_flags=green_flags,
        )

    def _calculate_dev_score(
        self,
        current_data,
        previous_data,
    ) -> tuple[float, float]:
        """
        Score development activity.

        Criteria:
        - Absolute activity level
        - Trend (growing vs declining)
        - Contributor diversity
        """
        if isinstance(current_data, Exception) or not current_data:
            return 50.0, 0.0

        current_avg = np.mean([d.dev_activity for d in current_data]) if current_data else 0
        prev_avg = np.mean([d.dev_activity for d in previous_data]) if previous_data and not isinstance(previous_data, Exception) else current_avg

        # Calculate trend
        trend = ((current_avg - prev_avg) / prev_avg * 100) if prev_avg > 0 else 0

        # Score based on activity level (normalized to typical ranges)
        # High activity projects: 100+, Low: <10
        activity_score = min(100, (current_avg / 50) * 100)

        # Bonus for positive trend
        trend_bonus = min(20, max(-20, trend / 5))

        # Contributor diversity bonus
        contributors = np.mean([d.dev_activity_contributors for d in current_data]) if current_data else 0
        diversity_bonus = min(10, contributors / 5)

        score = max(0, min(100, activity_score + trend_bonus + diversity_bonus))

        return score, trend

    def _calculate_holder_score(
        self,
        top_holders,
    ) -> tuple[float, float]:
        """
        Score holder distribution (decentralization).

        Criteria:
        - Top holder concentration (lower is better)
        - Distribution across tiers
        """
        if isinstance(top_holders, Exception) or not top_holders:
            return 50.0, 0.0

        # Calculate top 10 and top 100 concentration
        total_balance = sum(h.get("balance", 0) for h in top_holders)
        top_10_balance = sum(h.get("balance", 0) for h in top_holders[:10])
        top_100_balance = total_balance

        # Whale concentration as percentage (rough estimate)
        # In reality, we'd need total supply
        whale_concentration = (top_10_balance / total_balance * 100) if total_balance > 0 else 0

        # Score: Lower concentration = higher score
        # <20% top 10 = excellent, >60% = poor
        if whale_concentration < 20:
            score = 100 - whale_concentration
        elif whale_concentration < 40:
            score = 80 - (whale_concentration - 20)
        elif whale_concentration < 60:
            score = 60 - (whale_concentration - 40) * 1.5
        else:
            score = max(0, 30 - (whale_concentration - 60))

        return score, whale_concentration

    def _calculate_social_score(
        self,
        current_data,
        previous_data,
    ) -> tuple[float, float]:
        """
        Score social momentum.

        Criteria:
        - Social volume trend
        - Sentiment direction
        - Social dominance
        """
        if isinstance(current_data, Exception) or not current_data:
            return 50.0, 0.0

        current_volume = np.mean([d.social_volume for d in current_data]) if current_data else 0
        prev_volume = np.mean([d.social_volume for d in previous_data]) if previous_data and not isinstance(previous_data, Exception) else current_volume

        # Volume change
        volume_change = ((current_volume - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0

        # Sentiment score
        avg_sentiment = np.mean([d.sentiment_weighted for d in current_data]) if current_data else 0

        # Base score from sentiment (-1 to 1 mapped to 30-70)
        sentiment_score = 50 + (avg_sentiment * 20)

        # Bonus for growing social interest (capped)
        volume_bonus = min(25, max(-25, volume_change / 4))

        # Social dominance bonus
        dominance = np.mean([d.social_dominance for d in current_data]) if current_data else 0
        dominance_bonus = min(10, dominance * 2)

        score = max(0, min(100, sentiment_score + volume_bonus + dominance_bonus))

        return score, volume_change

    def _calculate_usage_score(
        self,
        current_data,
        previous_data,
    ) -> tuple[float, float]:
        """
        Score on-chain usage.

        Criteria:
        - Daily active addresses trend
        - Transaction volume
        - Network growth
        """
        if isinstance(current_data, Exception) or not current_data:
            return 50.0, 0.0

        current_daa = np.mean([d.daily_active_addresses for d in current_data]) if current_data else 0
        prev_daa = np.mean([d.daily_active_addresses for d in previous_data]) if previous_data and not isinstance(previous_data, Exception) else current_daa

        # DAA change
        daa_change = ((current_daa - prev_daa) / prev_daa * 100) if prev_daa > 0 else 0

        # Network growth
        current_growth = np.mean([d.network_growth for d in current_data]) if current_data else 0

        # Base score from DAA level (normalized)
        # High activity: 100k+, Low: <1k
        daa_score = min(60, (current_daa / 50000) * 60)

        # Trend bonus
        trend_bonus = min(25, max(-25, daa_change / 4))

        # Growth bonus
        growth_bonus = min(15, (current_growth / 10000) * 15)

        score = max(0, min(100, daa_score + trend_bonus + growth_bonus))

        return score, daa_change

    def _calculate_valuation_score(
        self,
        valuation_data,
    ) -> tuple[float, float]:
        """
        Score valuation based on MVRV ratio.

        MVRV interpretation:
        - < 1: Undervalued (historically good buy zone)
        - 1-2: Fair value
        - 2-3: Getting expensive
        - > 3: Overvalued (historically good sell zone)
        """
        if isinstance(valuation_data, Exception) or not valuation_data:
            return 50.0, 1.0

        latest_mvrv = valuation_data[-1].mvrv_ratio if valuation_data else 1.0

        # Score based on MVRV position
        # Undervalued = high score (good for buying)
        # Overvalued = low score (risky)
        if latest_mvrv < 0.7:
            score = 95  # Extreme undervaluation
        elif latest_mvrv < 1.0:
            score = 80 + (1.0 - latest_mvrv) * 50
        elif latest_mvrv < 1.5:
            score = 70 - (latest_mvrv - 1.0) * 20
        elif latest_mvrv < 2.0:
            score = 60 - (latest_mvrv - 1.5) * 30
        elif latest_mvrv < 3.0:
            score = 45 - (latest_mvrv - 2.0) * 20
        elif latest_mvrv < 4.0:
            score = 25 - (latest_mvrv - 3.0) * 15
        else:
            score = max(0, 10 - (latest_mvrv - 4.0) * 5)

        return score, latest_mvrv

    def _generate_red_flags(
        self,
        dev_trend: float,
        whale_concentration: float,
        social_change: float,
        daa_change: float,
        mvrv: float,
    ) -> list[str]:
        """Generate warning flags."""
        flags = []

        if dev_trend < -30:
            flags.append(f"Development activity declining ({dev_trend:.0f}%)")
        if whale_concentration > 50:
            flags.append(f"High whale concentration ({whale_concentration:.0f}% in top 10)")
        if social_change < -40:
            flags.append(f"Social interest fading ({social_change:.0f}%)")
        if daa_change < -30:
            flags.append(f"Network usage declining ({daa_change:.0f}%)")
        if mvrv > 3.5:
            flags.append(f"Historically overvalued (MVRV: {mvrv:.1f})")
        if mvrv > 4.5:
            flags.append("Extreme overvaluation - high risk zone")

        return flags

    def _generate_green_flags(
        self,
        dev_trend: float,
        whale_concentration: float,
        social_change: float,
        daa_change: float,
        mvrv: float,
    ) -> list[str]:
        """Generate positive flags."""
        flags = []

        if dev_trend > 30:
            flags.append(f"Strong development growth ({dev_trend:.0f}%)")
        if whale_concentration < 20:
            flags.append("Well-distributed token supply")
        if social_change > 50:
            flags.append(f"Growing social momentum ({social_change:.0f}%)")
        if daa_change > 30:
            flags.append(f"Increasing network adoption ({daa_change:.0f}%)")
        if mvrv < 1.0:
            flags.append(f"Undervalued territory (MVRV: {mvrv:.1f})")
        if 0.5 < mvrv < 0.8:
            flags.append("Strong accumulation zone historically")

        return flags

    async def calculate_batch(
        self,
        slugs: list[str],
        lookback_days: int = 30,
    ) -> list[HealthScore]:
        """Calculate health scores for multiple assets."""
        results = await asyncio.gather(
            *[self.calculate(slug, lookback_days) for slug in slugs],
            return_exceptions=True
        )

        return [r for r in results if isinstance(r, HealthScore)]

    async def get_top_by_health(
        self,
        slugs: list[str],
        top_n: int = 10,
        lookback_days: int = 30,
    ) -> list[HealthScore]:
        """Get top N assets by health score."""
        scores = await self.calculate_batch(slugs, lookback_days)
        scores.sort(key=lambda x: x.overall_score, reverse=True)
        return scores[:top_n]
