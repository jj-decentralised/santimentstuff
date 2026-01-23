"""
Narrative Analyzer

Combines Santiment data with LLM capabilities to generate
human-readable market narratives and insights.
"""

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from core.client import SantimentClient
from core.models import NarrativeInsight, TrendingWord
from .prompts import NarrativePrompts


@dataclass
class MarketContext:
    """Aggregated market context for narrative generation."""
    asset_slug: Optional[str]
    timestamp: datetime

    # Price data
    current_price: float = 0
    price_change_24h: float = 0
    price_change_7d: float = 0
    price_change_30d: float = 0

    # Sentiment data
    sentiment: float = 0
    sentiment_level: str = "neutral"
    social_volume: int = 0
    social_volume_change: float = 0

    # Trending topics
    trending_words: list[TrendingWord] = field(default_factory=list)

    # Whale data
    whale_flow_signal: str = "neutral"
    whale_net_flow: float = 0
    whale_total_inflow: float = 0
    whale_total_outflow: float = 0
    holder_behavior: str = "stable"
    holder_change_7d: float = 0

    # Valuation
    mvrv: float = 1.0

    # Dev activity
    dev_activity_trend: str = "stable"
    contributors: int = 0

    def to_price_dict(self) -> dict:
        return {
            "current_price": self.current_price,
            "change_24h": self.price_change_24h,
            "change_7d": self.price_change_7d,
            "change_30d": self.price_change_30d,
        }

    def to_sentiment_dict(self) -> dict:
        return {
            "sentiment": self.sentiment,
            "level": self.sentiment_level,
            "volume": self.social_volume,
            "volume_change": self.social_volume_change,
        }

    def to_whale_dict(self) -> dict:
        return {
            "flow_signal": self.whale_flow_signal,
            "net_flow": self.whale_net_flow,
            "total_inflow": self.whale_total_inflow,
            "total_outflow": self.whale_total_outflow,
            "holder_behavior": self.holder_behavior,
            "holder_change_7d": self.holder_change_7d,
        }


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, max_tokens: int = 1000) -> str:
        """Generate text from prompt."""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model

    async def generate(self, prompt: str, max_tokens: int = 1000) -> str:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=self.api_key)
            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return response.choices[0].message.content
        except ImportError:
            raise RuntimeError("openai package not installed")
        except Exception as e:
            raise RuntimeError(f"OpenAI API error: {e}")


class AnthropicProvider(LLMProvider):
    """Anthropic API provider."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-sonnet-20240229"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model

    async def generate(self, prompt: str, max_tokens: int = 1000) -> str:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self.api_key)
            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except ImportError:
            raise RuntimeError("anthropic package not installed")
        except Exception as e:
            raise RuntimeError(f"Anthropic API error: {e}")


class MockProvider(LLMProvider):
    """Mock provider for testing without API calls."""

    async def generate(self, prompt: str, max_tokens: int = 1000) -> str:
        # Generate a simple template response based on prompt content
        if "market narrative" in prompt.lower():
            return self._mock_market_narrative(prompt)
        elif "divergence" in prompt.lower():
            return self._mock_divergence()
        elif "trending" in prompt.lower():
            return self._mock_trending()
        elif "whale" in prompt.lower():
            return self._mock_whale()
        else:
            return self._mock_generic()

    def _mock_market_narrative(self, prompt: str) -> str:
        return """**Market Overview**

The asset is currently experiencing moderate trading activity with mixed signals across different metrics. Price action over the past week shows a consolidation pattern, suggesting the market is in a decision phase.

**Key Drivers**

Social sentiment has remained relatively stable, with no extreme readings that would typically precede major moves. Whale activity shows balanced exchange flows, indicating large holders are neither aggressively accumulating nor distributing.

**Outlook**

The current setup suggests a neutral bias with potential for increased volatility as the market awaits catalysts. Key levels to watch include recent support and resistance zones, while monitoring social sentiment for any sudden shifts that could precede directional moves."""

    def _mock_divergence(self) -> str:
        return """Based on the data provided, there appears to be a mild divergence between price action and sentiment. While prices have shown weakness, social sentiment has started improving - a pattern historically associated with potential trend reversals.

However, divergences alone are not reliable signals and should be confirmed with other indicators. The current divergence is moderate in strength, suggesting caution rather than immediate action."""

    def _mock_trending(self) -> str:
        return """The crypto community is currently focused on several key narratives: institutional adoption discussions, regulatory developments, and layer-2 scaling solutions. These topics are generating significant engagement across social platforms.

The trending discussions suggest market participants are weighing both bullish catalysts (ETF developments, enterprise adoption) and bearish concerns (regulatory scrutiny). This balanced narrative may explain current market consolidation."""

    def _mock_whale(self) -> str:
        return """Whale activity analysis shows a relatively balanced picture. Exchange inflows and outflows are roughly equal, suggesting large holders are not making aggressive directional bets at current prices.

Top holder positions have remained stable over the past week, which is typically a sign of confidence in current valuations. This stability in whale behavior often precedes periods of accumulation when prices dip."""

    def _mock_generic(self) -> str:
        return """Based on the available data, the market shows typical characteristics of a consolidation phase. Key metrics are within normal ranges, and no extreme readings suggest imminent major moves.

Continue monitoring key indicators for any significant deviations that could signal changing conditions."""


class NarrativeAnalyzer:
    """
    Main analyzer that combines Santiment data with LLM capabilities
    to generate market narratives.
    """

    def __init__(
        self,
        client: SantimentClient,
        llm_provider: Optional[LLMProvider] = None,
    ):
        self.client = client
        self.llm = llm_provider or MockProvider()
        self.prompts = NarrativePrompts()

    async def gather_context(
        self,
        asset_slug: str,
        include_trending: bool = True,
    ) -> MarketContext:
        """
        Gather all context needed for narrative generation.

        Args:
            asset_slug: Asset to analyze
            include_trending: Whether to include trending words

        Returns:
            MarketContext with all relevant data
        """
        now = datetime.utcnow()
        from_30d = now - timedelta(days=30)
        from_7d = now - timedelta(days=7)

        # Fetch all data in parallel
        tasks = [
            self.client.get_price(asset_slug, from_30d, now, "1d"),
            self.client.get_sentiment(asset_slug, from_7d, now, "1d"),
            self.client.get_exchange_flow(asset_slug, from_7d, now, "1d"),
            self.client.get_valuation_metrics(asset_slug, from_7d, now, "1d"),
            self.client.get_dev_activity(asset_slug, from_30d, now, "1d"),
            self.client.get_top_holders(asset_slug, 100),
        ]

        if include_trending:
            tasks.append(self.client.get_trending_words(24, 20))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Unpack results
        price_data = results[0] if not isinstance(results[0], Exception) else []
        sentiment_data = results[1] if not isinstance(results[1], Exception) else []
        exchange_flow = results[2] if not isinstance(results[2], Exception) else []
        valuation = results[3] if not isinstance(results[3], Exception) else []
        dev_activity = results[4] if not isinstance(results[4], Exception) else []
        top_holders = results[5] if not isinstance(results[5], Exception) else []
        trending = results[6] if len(results) > 6 and not isinstance(results[6], Exception) else []

        # Build context
        context = MarketContext(
            asset_slug=asset_slug,
            timestamp=now,
        )

        # Price data
        if price_data:
            current = price_data[-1]
            context.current_price = current.get("closePriceUsd", 0)

            if len(price_data) > 1:
                prev_24h = price_data[-2].get("closePriceUsd", context.current_price)
                context.price_change_24h = ((context.current_price - prev_24h) / prev_24h * 100) if prev_24h else 0

            if len(price_data) > 7:
                prev_7d = price_data[-8].get("closePriceUsd", context.current_price)
                context.price_change_7d = ((context.current_price - prev_7d) / prev_7d * 100) if prev_7d else 0

            if len(price_data) > 29:
                prev_30d = price_data[0].get("closePriceUsd", context.current_price)
                context.price_change_30d = ((context.current_price - prev_30d) / prev_30d * 100) if prev_30d else 0

        # Sentiment data
        if sentiment_data:
            latest = sentiment_data[-1]
            context.sentiment = latest.sentiment_weighted
            context.sentiment_level = latest.sentiment_level.value
            context.social_volume = latest.social_volume

            if len(sentiment_data) > 1:
                prev_volume = sentiment_data[-2].social_volume
                context.social_volume_change = ((latest.social_volume - prev_volume) / prev_volume * 100) if prev_volume else 0

        # Exchange flow
        if exchange_flow:
            total_inflow = sum(f.inflow for f in exchange_flow)
            total_outflow = sum(f.outflow for f in exchange_flow)
            net_flow = total_inflow - total_outflow

            context.whale_total_inflow = total_inflow
            context.whale_total_outflow = total_outflow
            context.whale_net_flow = net_flow

            if net_flow > total_inflow * 0.1:
                context.whale_flow_signal = "bearish"
            elif net_flow < -total_outflow * 0.1:
                context.whale_flow_signal = "bullish"
            else:
                context.whale_flow_signal = "neutral"

        # Valuation
        if valuation:
            context.mvrv = valuation[-1].mvrv_ratio

        # Dev activity
        if dev_activity:
            latest_dev = dev_activity[-1]
            context.contributors = latest_dev.contributors_count

            if len(dev_activity) > 7:
                recent = sum(d.dev_activity for d in dev_activity[-7:])
                prev = sum(d.dev_activity for d in dev_activity[-14:-7]) if len(dev_activity) > 14 else recent
                if recent > prev * 1.2:
                    context.dev_activity_trend = "increasing"
                elif recent < prev * 0.8:
                    context.dev_activity_trend = "decreasing"
                else:
                    context.dev_activity_trend = "stable"

        # Top holders
        if top_holders:
            change_7d = sum(h.get("balanceChange7d", 0) for h in top_holders[:10])
            if change_7d > 0:
                context.holder_behavior = "accumulating"
            elif change_7d < 0:
                context.holder_behavior = "distributing"
            else:
                context.holder_behavior = "stable"
            context.holder_change_7d = change_7d

        # Trending words
        context.trending_words = trending

        return context

    async def generate_narrative(
        self,
        asset_slug: str,
    ) -> NarrativeInsight:
        """
        Generate a full market narrative for an asset.

        Args:
            asset_slug: Asset to analyze

        Returns:
            NarrativeInsight with the generated narrative
        """
        context = await self.gather_context(asset_slug)

        # Generate prompt
        prompt = self.prompts.market_narrative(
            asset=asset_slug,
            price_data=context.to_price_dict(),
            sentiment_data=context.to_sentiment_dict(),
            trending_words=[w.word for w in context.trending_words],
            whale_data=context.to_whale_dict(),
        )

        # Generate narrative
        narrative_text = await self.llm.generate(prompt)

        # Extract key drivers from context
        key_drivers = []
        if abs(context.price_change_7d) > 10:
            direction = "rally" if context.price_change_7d > 0 else "decline"
            key_drivers.append(f"Price {direction} of {abs(context.price_change_7d):.1f}%")
        if context.sentiment_level in ["extreme_fear", "extreme_greed"]:
            key_drivers.append(f"{context.sentiment_level.replace('_', ' ').title()} sentiment")
        if context.whale_flow_signal != "neutral":
            key_drivers.append(f"{context.whale_flow_signal.title()} whale activity")
        if context.holder_behavior != "stable":
            key_drivers.append(f"Top holders {context.holder_behavior}")

        # Check alignment
        price_direction = "up" if context.price_change_7d > 0 else "down"
        sentiment_direction = "positive" if context.sentiment > 0 else "negative"
        sentiment_alignment = (price_direction == "up" and sentiment_direction == "positive") or \
                             (price_direction == "down" and sentiment_direction == "negative")

        return NarrativeInsight(
            datetime=context.timestamp,
            asset_slug=asset_slug,
            narrative=narrative_text,
            key_drivers=key_drivers or ["No dominant drivers identified"],
            sentiment_alignment=sentiment_alignment,
            trending_topics=context.trending_words[:5],
            confidence_score=self._calculate_confidence(context),
            price_change_24h=context.price_change_24h,
            social_volume_change=context.social_volume_change,
            whale_activity_summary=f"{context.whale_flow_signal} - Net flow: ${context.whale_net_flow:,.0f}",
        )

    async def generate_divergence_analysis(
        self,
        asset_slug: str,
    ) -> dict:
        """Generate focused divergence analysis."""
        context = await self.gather_context(asset_slug, include_trending=False)

        # Check for divergence
        has_divergence = False
        divergence_type = None

        if context.price_change_7d > 10 and context.sentiment < -0.1:
            has_divergence = True
            divergence_type = "bearish"
        elif context.price_change_7d < -10 and context.sentiment > 0.1:
            has_divergence = True
            divergence_type = "bullish"

        prompt = self.prompts.divergence_analysis(
            asset=asset_slug,
            price_change=context.price_change_7d,
            sentiment=context.sentiment,
            sentiment_change=context.social_volume_change / 100,  # Approximate
        )

        analysis = await self.llm.generate(prompt)

        return {
            "asset": asset_slug,
            "has_divergence": has_divergence,
            "divergence_type": divergence_type,
            "price_change_7d": context.price_change_7d,
            "sentiment": context.sentiment,
            "analysis": analysis,
            "generated_at": context.timestamp.isoformat(),
        }

    async def generate_trending_summary(self) -> dict:
        """Generate summary of trending topics market-wide."""
        trending = await self.client.get_trending_words(24, 20)

        # Try to associate with assets
        associated_assets = []
        for word in trending:
            word_lower = word.word.lower()
            if word_lower in ["bitcoin", "btc"]:
                associated_assets.append("bitcoin")
            elif word_lower in ["ethereum", "eth"]:
                associated_assets.append("ethereum")
            elif word_lower in ["solana", "sol"]:
                associated_assets.append("solana")
            # Add more mappings as needed

        prompt = self.prompts.trending_topics_summary(
            trending_words=[{"word": w.word, "hype_score": w.hype_score} for w in trending],
            associated_assets=list(set(associated_assets)),
        )

        summary = await self.llm.generate(prompt)

        return {
            "trending_words": [
                {"word": w.word, "hype_score": w.hype_score}
                for w in trending
            ],
            "associated_assets": list(set(associated_assets)),
            "summary": summary,
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def generate_whale_summary(
        self,
        asset_slug: str,
    ) -> dict:
        """Generate whale activity summary."""
        context = await self.gather_context(asset_slug, include_trending=False)

        prompt = self.prompts.whale_activity_summary(
            whale_data=context.to_whale_dict(),
            recent_large_transactions=[],  # Would need actual transaction data
        )

        summary = await self.llm.generate(prompt)

        return {
            "asset": asset_slug,
            "flow_signal": context.whale_flow_signal,
            "net_flow": context.whale_net_flow,
            "holder_behavior": context.holder_behavior,
            "summary": summary,
            "generated_at": context.timestamp.isoformat(),
        }

    def _calculate_confidence(self, context: MarketContext) -> float:
        """
        Calculate confidence score for the narrative.

        Higher confidence when:
        - Strong price movement
        - Clear sentiment signal
        - Whale activity aligns with sentiment
        - High social volume
        """
        confidence = 0.5  # Base confidence

        # Price clarity
        if abs(context.price_change_7d) > 10:
            confidence += 0.1

        # Sentiment clarity
        if abs(context.sentiment) > 0.3:
            confidence += 0.1

        # Alignment bonus
        price_up = context.price_change_7d > 0
        sentiment_positive = context.sentiment > 0
        whale_bullish = context.whale_flow_signal == "bullish"
        holders_accumulating = context.holder_behavior == "accumulating"

        alignments = sum([
            price_up == sentiment_positive,
            price_up == whale_bullish,
            price_up == holders_accumulating,
        ])

        confidence += alignments * 0.05

        # Social volume bonus
        if context.social_volume > 1000:
            confidence += 0.05
        if context.social_volume > 5000:
            confidence += 0.05

        return min(0.95, confidence)

    def set_llm_provider(self, provider: LLMProvider) -> None:
        """Change the LLM provider."""
        self.llm = provider
