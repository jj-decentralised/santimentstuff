"""
Narrative Analyzer

Generates human-readable market narratives using Santiment data
with intelligent template-based generation.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from core.client import SantimentClient
from core.models import NarrativeInsight, TrendingWord


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


class NarrativeGenerator:
    """Generates data-driven narratives from market context."""

    def generate_market_narrative(self, ctx: MarketContext) -> str:
        """Generate a market narrative based on actual data."""
        asset = ctx.asset_slug.upper() if ctx.asset_slug else "The asset"

        # Price section
        if ctx.price_change_7d > 15:
            price_text = f"{asset} has seen a strong rally of {ctx.price_change_7d:.1f}% over the past week, currently trading at ${ctx.current_price:,.2f}."
        elif ctx.price_change_7d > 5:
            price_text = f"{asset} is up {ctx.price_change_7d:.1f}% this week, trading at ${ctx.current_price:,.2f}."
        elif ctx.price_change_7d < -15:
            price_text = f"{asset} has dropped {abs(ctx.price_change_7d):.1f}% over the past week to ${ctx.current_price:,.2f}."
        elif ctx.price_change_7d < -5:
            price_text = f"{asset} is down {abs(ctx.price_change_7d):.1f}% this week at ${ctx.current_price:,.2f}."
        else:
            price_text = f"{asset} is consolidating around ${ctx.current_price:,.2f} with minimal movement ({ctx.price_change_7d:+.1f}% this week)."

        # Sentiment section
        if ctx.sentiment > 0.3:
            sentiment_text = "Social sentiment is strongly positive, indicating bullish crowd psychology."
        elif ctx.sentiment > 0.1:
            sentiment_text = "Social sentiment leans positive with moderate optimism in the community."
        elif ctx.sentiment < -0.3:
            sentiment_text = "Social sentiment is notably negative, reflecting fear or pessimism."
        elif ctx.sentiment < -0.1:
            sentiment_text = "Social sentiment leans negative with some caution in discussions."
        else:
            sentiment_text = "Social sentiment is neutral with no strong directional bias."

        # Volume context
        if ctx.social_volume_change > 50:
            volume_text = f" Social volume has spiked {ctx.social_volume_change:.0f}%, suggesting heightened interest."
        elif ctx.social_volume_change < -30:
            volume_text = f" Social volume has declined {abs(ctx.social_volume_change):.0f}%, indicating reduced attention."
        else:
            volume_text = ""

        # Whale section
        if ctx.whale_flow_signal == "bullish":
            whale_text = f"Whale activity is bullish with net outflows of ${abs(ctx.whale_net_flow):,.0f} from exchanges, suggesting accumulation."
        elif ctx.whale_flow_signal == "bearish":
            whale_text = f"Whale activity shows warning signs with ${ctx.whale_net_flow:,.0f} net inflows to exchanges, potentially signaling distribution."
        else:
            whale_text = "Exchange flows are balanced with no strong directional whale activity."

        # Holder behavior
        if ctx.holder_behavior == "accumulating":
            holder_text = " Top holders have been increasing their positions."
        elif ctx.holder_behavior == "distributing":
            holder_text = " Top holders appear to be reducing exposure."
        else:
            holder_text = ""

        # MVRV context
        if ctx.mvrv < 0.8:
            valuation_text = f"The MVRV ratio at {ctx.mvrv:.2f} suggests the asset may be undervalued historically."
        elif ctx.mvrv > 3.0:
            valuation_text = f"The MVRV ratio at {ctx.mvrv:.2f} indicates potential overvaluation - caution advised."
        elif ctx.mvrv > 2.0:
            valuation_text = f"The MVRV ratio at {ctx.mvrv:.2f} shows healthy profit levels in the market."
        else:
            valuation_text = f"Valuation metrics (MVRV: {ctx.mvrv:.2f}) are within normal ranges."

        # Combine sections
        narrative = f"""**Market Overview**

{price_text} {sentiment_text}{volume_text}

**On-Chain Analysis**

{whale_text}{holder_text} {valuation_text}

**Development & Activity**

Development activity is {ctx.dev_activity_trend} with {ctx.contributors} active contributors. {"This signals ongoing project commitment." if ctx.dev_activity_trend == "increasing" else "Activity levels are being maintained." if ctx.dev_activity_trend == "stable" else "Reduced development activity warrants monitoring."}"""

        return narrative

    def generate_divergence_narrative(self, ctx: MarketContext) -> str:
        """Generate divergence analysis narrative."""
        has_divergence = False
        divergence_type = None

        if ctx.price_change_7d > 10 and ctx.sentiment < -0.1:
            has_divergence = True
            divergence_type = "bearish"
        elif ctx.price_change_7d < -10 and ctx.sentiment > 0.1:
            has_divergence = True
            divergence_type = "bullish"

        if has_divergence:
            if divergence_type == "bullish":
                return f"""A bullish divergence is detected: price has declined {abs(ctx.price_change_7d):.1f}% but sentiment remains positive ({ctx.sentiment:.2f}).

Historically, this pattern can precede price recoveries as the crowd sentiment leads price action. The negative price movement may present accumulation opportunities if sentiment continues to improve."""
            else:
                return f"""A bearish divergence is detected: price has risen {ctx.price_change_7d:.1f}% but sentiment is negative ({ctx.sentiment:.2f}).

This disconnect between price and sentiment can signal unsustainable rallies. When the crowd is pessimistic despite rising prices, it may indicate distribution by informed participants."""
        else:
            return f"""No significant divergence detected. Price ({ctx.price_change_7d:+.1f}% 7d) and sentiment ({ctx.sentiment:.2f}) are relatively aligned.

The market appears to be pricing in the current sentiment accurately, suggesting continuation of the prevailing trend unless external catalysts emerge."""

    def generate_whale_narrative(self, ctx: MarketContext) -> str:
        """Generate whale activity narrative."""
        net_flow_str = f"${abs(ctx.whale_net_flow):,.0f}"

        if ctx.whale_flow_signal == "bullish":
            flow_text = f"Exchange outflows dominate with {net_flow_str} net withdrawals. Large holders are moving assets to cold storage, a classic accumulation signal."
        elif ctx.whale_flow_signal == "bearish":
            flow_text = f"Exchange inflows are elevated with {net_flow_str} net deposits. This increases available supply for selling and often precedes downward pressure."
        else:
            flow_text = f"Exchange flows are balanced (net: {net_flow_str}). Whales appear to be in a wait-and-see mode."

        if ctx.holder_behavior == "accumulating":
            holder_text = "Top 10 holders have increased positions over the past week, confirming accumulation patterns."
        elif ctx.holder_behavior == "distributing":
            holder_text = "Top 10 holders have reduced positions, suggesting some profit-taking or rebalancing."
        else:
            holder_text = "Top holder positions remain stable with no significant changes."

        return f"""**Exchange Flow Analysis**

{flow_text}

**Top Holder Behavior**

{holder_text}

**Summary**

{"Whale behavior is supportive of higher prices." if ctx.whale_flow_signal == "bullish" else "Whale positioning suggests caution." if ctx.whale_flow_signal == "bearish" else "No strong directional signal from whale activity."}"""

    def generate_trending_narrative(self, trending_words: list, associated_assets: list) -> str:
        """Generate trending topics narrative."""
        if not trending_words:
            return "No significant trending topics detected in crypto social media at this time."

        top_words = [w.get("word", "") for w in trending_words[:5]]
        words_str = ", ".join(top_words)

        return f"""**Trending Topics**

The crypto community is currently discussing: {words_str}

{"These topics are associated with: " + ", ".join(associated_assets) if associated_assets else "These topics span multiple assets and general market themes."}

**Market Implications**

Trending discussions often reflect near-term catalysts and sentiment drivers. Elevated social volume around specific topics can precede volatility as narratives spread through the market."""


class NarrativeAnalyzer:
    """
    Main analyzer that combines Santiment data to generate
    market narratives using intelligent templates.
    """

    def __init__(self, client: SantimentClient):
        self.client = client
        self.generator = NarrativeGenerator()

    async def gather_context(
        self,
        asset_slug: str,
        include_trending: bool = True,
    ) -> MarketContext:
        """Gather all context needed for narrative generation."""
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

    async def generate_narrative(self, asset_slug: str) -> NarrativeInsight:
        """Generate a full market narrative for an asset."""
        context = await self.gather_context(asset_slug)

        # Generate narrative using templates
        narrative_text = self.generator.generate_market_narrative(context)

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

    async def generate_divergence_analysis(self, asset_slug: str) -> dict:
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

        analysis = self.generator.generate_divergence_narrative(context)

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

        trending_dicts = [{"word": w.word, "hype_score": w.hype_score} for w in trending]
        summary = self.generator.generate_trending_narrative(trending_dicts, list(set(associated_assets)))

        return {
            "trending_words": trending_dicts,
            "associated_assets": list(set(associated_assets)),
            "summary": summary,
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def generate_whale_summary(self, asset_slug: str) -> dict:
        """Generate whale activity summary."""
        context = await self.gather_context(asset_slug, include_trending=False)

        summary = self.generator.generate_whale_narrative(context)

        return {
            "asset": asset_slug,
            "flow_signal": context.whale_flow_signal,
            "net_flow": context.whale_net_flow,
            "holder_behavior": context.holder_behavior,
            "summary": summary,
            "generated_at": context.timestamp.isoformat(),
        }

    def _calculate_confidence(self, context: MarketContext) -> float:
        """Calculate confidence score for the narrative."""
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
