"""
Prompt Templates for Market Narrative Generation

These prompts are designed to work with any LLM API (OpenAI, Anthropic, etc.)
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class NarrativePrompts:
    """Collection of prompts for different narrative types."""

    @staticmethod
    def market_narrative(
        asset: str,
        price_data: dict,
        sentiment_data: dict,
        trending_words: list[str],
        whale_data: dict,
    ) -> str:
        """
        Generate prompt for overall market narrative.
        """
        return f"""You are a crypto market analyst. Generate a concise market narrative for {asset.upper()} based on the following data:

## Price Action
- Current Price: ${price_data.get('current_price', 'N/A'):,.2f}
- 24h Change: {price_data.get('change_24h', 0):+.1f}%
- 7d Change: {price_data.get('change_7d', 0):+.1f}%
- 30d Change: {price_data.get('change_30d', 0):+.1f}%

## Social Sentiment
- Sentiment Score: {sentiment_data.get('sentiment', 0):.2f} (scale: -1 bearish to +1 bullish)
- Sentiment Level: {sentiment_data.get('level', 'neutral')}
- Social Volume: {sentiment_data.get('volume', 0):,} mentions
- Social Volume Change: {sentiment_data.get('volume_change', 0):+.1f}%

## Trending Topics
{', '.join(trending_words[:10]) if trending_words else 'No specific trending topics'}

## Whale Activity
- Exchange Flow: {whale_data.get('flow_signal', 'neutral')}
- Net Flow: ${whale_data.get('net_flow', 0):,.0f}
- Top Holders: {whale_data.get('holder_behavior', 'stable')}

Generate a 2-3 paragraph narrative that:
1. Explains the current market situation
2. Identifies the key drivers of recent price movement
3. Notes any divergences between price and sentiment
4. Provides a balanced outlook

Keep it factual and avoid hyperbole. Use the data provided to support your analysis."""

    @staticmethod
    def divergence_analysis(
        asset: str,
        price_change: float,
        sentiment: float,
        sentiment_change: float,
    ) -> str:
        """Generate prompt for divergence analysis."""
        return f"""Analyze the price-sentiment divergence for {asset.upper()}:

Price Movement: {price_change:+.1f}% over 7 days
Current Sentiment: {sentiment:.2f} (-1 to +1 scale)
Sentiment Change: {sentiment_change:+.2f} over 24 hours

Identify:
1. Is there a divergence? (price and sentiment moving opposite directions)
2. What type? (bullish divergence = price down, sentiment up; bearish = opposite)
3. Historical significance of such divergences
4. What this might signal for near-term price action

Be specific and data-driven. 2 paragraphs maximum."""

    @staticmethod
    def trending_topics_summary(
        trending_words: list[dict],
        associated_assets: list[str],
    ) -> str:
        """Generate prompt for trending topics summary."""
        words_formatted = "\n".join([
            f"- {w.get('word', '')}: Hype Score {w.get('hype_score', 0):.1f}"
            for w in trending_words[:15]
        ])

        return f"""Summarize the current trending topics in crypto social media:

## Top Trending Words (by hype score)
{words_formatted}

## Associated Assets
{', '.join(associated_assets[:10]) if associated_assets else 'Various'}

Provide:
1. A brief summary of what the crypto community is discussing
2. Which topics might be driving market sentiment
3. Any notable narratives forming (ETF news, regulation, protocol updates, etc.)
4. Which assets might be most affected by current discussions

Keep it concise - 2 paragraphs maximum."""

    @staticmethod
    def whale_activity_summary(
        whale_data: dict,
        recent_large_transactions: list[dict],
    ) -> str:
        """Generate prompt for whale activity summary."""
        tx_formatted = "\n".join([
            f"- ${t.get('value_usd', 0):,.0f} {t.get('type', 'transfer')}"
            for t in recent_large_transactions[:10]
        ])

        return f"""Summarize recent whale activity:

## Exchange Flow Analysis
- Signal: {whale_data.get('flow_signal', 'neutral')}
- Net Flow: ${whale_data.get('net_flow', 0):,.0f}
- Total Inflow: ${whale_data.get('total_inflow', 0):,.0f}
- Total Outflow: ${whale_data.get('total_outflow', 0):,.0f}

## Top Holder Behavior
- Trend: {whale_data.get('holder_behavior', 'stable')}
- 7d Change: {whale_data.get('holder_change_7d', 0):+.1f}%

## Recent Large Transactions
{tx_formatted if tx_formatted else 'No significant transactions'}

Explain:
1. What whales appear to be doing (accumulating/distributing)
2. The potential market impact
3. Historical context for similar patterns

Keep it factual. 2 paragraphs maximum."""

    @staticmethod
    def investment_thesis(
        asset: str,
        health_score: dict,
        valuation: dict,
        dev_activity: dict,
    ) -> str:
        """Generate prompt for investment thesis."""
        return f"""Generate a balanced investment thesis for {asset.upper()}:

## Health Score: {health_score.get('overall', 50)}/100 (Grade: {health_score.get('grade', 'C')})
- Development: {health_score.get('dev_score', 50)}/100
- Distribution: {health_score.get('distribution_score', 50)}/100
- Social: {health_score.get('social_score', 50)}/100
- Usage: {health_score.get('usage_score', 50)}/100
- Valuation: {health_score.get('valuation_score', 50)}/100

## Valuation Metrics
- MVRV Ratio: {valuation.get('mvrv', 1):.2f}
- Historical MVRV Range: 0.5 (oversold) to 3.5 (overbought)

## Development Activity
- Trend: {dev_activity.get('trend', 'stable')}
- Contributors: {dev_activity.get('contributors', 0)}

## Flags
Red Flags: {', '.join(health_score.get('red_flags', [])) or 'None'}
Green Flags: {', '.join(health_score.get('green_flags', [])) or 'None'}

Provide:
1. Bull case (2-3 points)
2. Bear case (2-3 points)
3. Key metrics to watch
4. Risk assessment (Low/Medium/High)

Be balanced and objective. Avoid recommending specific actions."""

    @staticmethod
    def market_summary(
        top_gainers: list[dict],
        top_losers: list[dict],
        trending_narratives: list[str],
        overall_sentiment: str,
    ) -> str:
        """Generate prompt for daily market summary."""
        gainers = "\n".join([
            f"- {g.get('asset', '')}: +{g.get('change', 0):.1f}%"
            for g in top_gainers[:5]
        ])
        losers = "\n".join([
            f"- {l.get('asset', '')}: {l.get('change', 0):.1f}%"
            for l in top_losers[:5]
        ])

        return f"""Generate a daily crypto market summary:

## Market Sentiment: {overall_sentiment}

## Top Gainers (24h)
{gainers if gainers else 'No significant gainers'}

## Top Losers (24h)
{losers if losers else 'No significant losers'}

## Trending Narratives
{', '.join(trending_narratives[:5]) if trending_narratives else 'No dominant narratives'}

Write a concise market summary covering:
1. Overall market condition
2. Key movers and why they're moving
3. Dominant narratives driving the market
4. What to watch in the next 24 hours

Professional tone. 3 paragraphs maximum."""
