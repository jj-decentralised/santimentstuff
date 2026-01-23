"""
Research Terminal

Unified interface combining all analysis products into
a comprehensive research terminal.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from core.client import SantimentClient
from core.cache import CacheManager
from products.health_score.calculator import HealthScoreCalculator
from products.whale_watch.tracker import WhaleTracker
from products.sentiment_bot.signals import SignalGenerator
from products.sentiment_bot.strategy import StrategyConfig
from products.narrative_ai.analyzer import NarrativeAnalyzer, MockProvider
from .screener import AssetScreener


@dataclass
class AssetReport:
    """Comprehensive report for a single asset."""
    slug: str
    name: str
    ticker: str
    generated_at: datetime

    # Price data
    price: float
    price_change_24h: float
    price_change_7d: float
    market_cap: float

    # Health score
    health_score: float
    health_grade: str
    health_components: dict
    health_flags: dict

    # Whale data
    whale_sentiment: str
    exchange_net_flow: float
    holder_behavior: str

    # Sentiment & signals
    sentiment: float
    sentiment_level: str
    trading_signal: Optional[dict]

    # AI narrative
    narrative: str
    key_drivers: list[str]

    def to_dict(self) -> dict:
        return {
            "asset": {
                "slug": self.slug,
                "name": self.name,
                "ticker": self.ticker,
            },
            "generated_at": self.generated_at.isoformat(),
            "price": {
                "current": self.price,
                "change_24h": self.price_change_24h,
                "change_7d": self.price_change_7d,
                "market_cap": self.market_cap,
            },
            "health": {
                "score": self.health_score,
                "grade": self.health_grade,
                "components": self.health_components,
                "flags": self.health_flags,
            },
            "whale_activity": {
                "sentiment": self.whale_sentiment,
                "net_flow": self.exchange_net_flow,
                "holder_behavior": self.holder_behavior,
            },
            "social": {
                "sentiment": self.sentiment,
                "level": self.sentiment_level,
            },
            "signal": self.trading_signal,
            "narrative": {
                "text": self.narrative,
                "key_drivers": self.key_drivers,
            },
        }


@dataclass
class MarketOverview:
    """Market-wide overview combining multiple data points."""
    generated_at: datetime

    # Top movers
    top_gainers: list[dict]
    top_losers: list[dict]

    # Sentiment overview
    market_sentiment: str
    fear_greed_index: float

    # Whale activity
    bullish_assets: list[str]
    bearish_assets: list[str]

    # Trending
    trending_topics: list[str]

    # Top opportunities
    undervalued_assets: list[dict]
    high_activity_assets: list[dict]

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "movers": {
                "gainers": self.top_gainers,
                "losers": self.top_losers,
            },
            "sentiment": {
                "overall": self.market_sentiment,
                "fear_greed": self.fear_greed_index,
            },
            "whale_signals": {
                "bullish": self.bullish_assets,
                "bearish": self.bearish_assets,
            },
            "trending": self.trending_topics,
            "opportunities": {
                "undervalued": self.undervalued_assets,
                "high_activity": self.high_activity_assets,
            },
        }


class ResearchTerminal:
    """
    Unified research terminal combining all analysis products.

    Usage:
        async with ResearchTerminal() as terminal:
            report = await terminal.get_asset_report("bitcoin")
            overview = await terminal.get_market_overview()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        use_redis: bool = False,
    ):
        self._api_key = api_key
        self._use_redis = use_redis
        self._client: Optional[SantimentClient] = None

        # Product instances
        self._health_calculator: Optional[HealthScoreCalculator] = None
        self._whale_tracker: Optional[WhaleTracker] = None
        self._signal_generator: Optional[SignalGenerator] = None
        self._narrative_analyzer: Optional[NarrativeAnalyzer] = None
        self._screener: Optional[AssetScreener] = None

    async def __aenter__(self):
        cache = CacheManager.create(use_redis=self._use_redis)
        self._client = SantimentClient(api_key=self._api_key, cache=cache)
        await self._client.__aenter__()

        # Initialize all products
        self._health_calculator = HealthScoreCalculator(self._client)
        self._whale_tracker = WhaleTracker(self._client)
        self._signal_generator = SignalGenerator(self._client)
        self._narrative_analyzer = NarrativeAnalyzer(self._client, MockProvider())
        self._screener = AssetScreener(self._client)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def get_asset_report(
        self,
        slug: str,
    ) -> AssetReport:
        """
        Generate a comprehensive report for a single asset.

        Combines data from all analysis products into one report.
        """
        # Fetch all data in parallel
        health, whale_dashboard, signal, narrative, asset = await asyncio.gather(
            self._health_calculator.calculate(slug),
            self._whale_tracker.get_whale_dashboard(slug),
            self._signal_generator.generate_signal(slug),
            self._narrative_analyzer.generate_narrative(slug),
            self._client.get_asset(slug),
            return_exceptions=True,
        )

        # Get price data
        now = datetime.utcnow()
        price_data = await self._client.get_price(
            slug, now - timedelta(days=7), now, "1d"
        )

        current_price = 0
        price_change_24h = 0
        price_change_7d = 0

        if price_data:
            current_price = price_data[-1].get("closePriceUsd", 0)
            if len(price_data) > 1:
                prev_24h = price_data[-2].get("closePriceUsd", current_price)
                price_change_24h = ((current_price - prev_24h) / prev_24h * 100) if prev_24h else 0
            if len(price_data) > 6:
                prev_7d = price_data[0].get("closePriceUsd", current_price)
                price_change_7d = ((current_price - prev_7d) / prev_7d * 100) if prev_7d else 0

        # Build report
        return AssetReport(
            slug=slug,
            name=asset.name if asset and not isinstance(asset, Exception) else slug,
            ticker=asset.ticker if asset and not isinstance(asset, Exception) else slug.upper(),
            generated_at=now,
            price=current_price,
            price_change_24h=round(price_change_24h, 2),
            price_change_7d=round(price_change_7d, 2),
            market_cap=asset.market_cap_usd if asset and not isinstance(asset, Exception) else 0,
            health_score=health.overall_score if not isinstance(health, Exception) else 50,
            health_grade=health.grade if not isinstance(health, Exception) else "C",
            health_components={
                "development": health.dev_activity_score if not isinstance(health, Exception) else 50,
                "distribution": health.holder_distribution_score if not isinstance(health, Exception) else 50,
                "social": health.social_momentum_score if not isinstance(health, Exception) else 50,
                "usage": health.onchain_usage_score if not isinstance(health, Exception) else 50,
                "valuation": health.valuation_score if not isinstance(health, Exception) else 50,
            },
            health_flags={
                "red": health.red_flags if not isinstance(health, Exception) else [],
                "green": health.green_flags if not isinstance(health, Exception) else [],
            },
            whale_sentiment=whale_dashboard.get("overall_sentiment", "neutral") if not isinstance(whale_dashboard, Exception) else "neutral",
            exchange_net_flow=whale_dashboard.get("exchange_flows", {}).get("flows", {}).get("net_flow", 0) if not isinstance(whale_dashboard, Exception) else 0,
            holder_behavior=whale_dashboard.get("top_holders", {}).get("behavior", {}).get("accumulating", False) and "accumulating" or "stable" if not isinstance(whale_dashboard, Exception) else "stable",
            sentiment=narrative.trending_topics[0].hype_score if not isinstance(narrative, Exception) and narrative.trending_topics else 0,
            sentiment_level="neutral",
            trading_signal=signal.to_dict() if signal and not isinstance(signal, Exception) else None,
            narrative=narrative.narrative if not isinstance(narrative, Exception) else "Unable to generate narrative.",
            key_drivers=narrative.key_drivers if not isinstance(narrative, Exception) else [],
        )

    async def get_market_overview(self) -> MarketOverview:
        """
        Generate a market-wide overview.

        Scans top assets for movers, sentiment, and opportunities.
        """
        top_assets = [
            "bitcoin", "ethereum", "ripple", "cardano", "solana",
            "polkadot", "avalanche", "polygon", "chainlink", "uniswap",
            "litecoin", "cosmos", "algorand", "near-protocol", "fantom",
        ]

        # Get price data for all assets
        now = datetime.utcnow()
        from_date = now - timedelta(days=7)

        price_tasks = [
            self._client.get_price(slug, from_date, now, "1d")
            for slug in top_assets
        ]

        price_results = await asyncio.gather(*price_tasks, return_exceptions=True)

        # Calculate movers
        movers = []
        for slug, prices in zip(top_assets, price_results):
            if isinstance(prices, Exception) or not prices:
                continue

            current = prices[-1].get("closePriceUsd", 0)
            if len(prices) > 1 and current > 0:
                prev = prices[-2].get("closePriceUsd", current)
                change = ((current - prev) / prev * 100) if prev else 0
                movers.append({
                    "asset": slug,
                    "price": current,
                    "change_24h": round(change, 2),
                })

        movers.sort(key=lambda x: x["change_24h"], reverse=True)
        top_gainers = movers[:5]
        top_losers = movers[-5:][::-1]

        # Get whale signals
        whale_tasks = [
            self._whale_tracker.get_exchange_flow_analysis(slug, days=7)
            for slug in top_assets[:10]
        ]
        whale_results = await asyncio.gather(*whale_tasks, return_exceptions=True)

        bullish_assets = []
        bearish_assets = []

        for slug, result in zip(top_assets[:10], whale_results):
            if isinstance(result, Exception):
                continue
            if result.signal == "bullish":
                bullish_assets.append(slug)
            elif result.signal == "bearish":
                bearish_assets.append(slug)

        # Get trending
        trending = await self._client.get_trending_words(24, 10)
        trending_topics = [w.word for w in trending] if trending else []

        # Run screeners for opportunities
        try:
            undervalued = await self._screener.quick_screen("undervalued")
            undervalued_assets = [
                {"asset": r.slug, "mvrv": r.metrics.get("mvrv", 1)}
                for r in undervalued[:5]
            ]
        except Exception:
            undervalued_assets = []

        try:
            high_activity = await self._screener.quick_screen("high_activity")
            high_activity_assets = [
                {"asset": r.slug, "daa": r.metrics.get("daily_active_addresses", 0)}
                for r in high_activity[:5]
            ]
        except Exception:
            high_activity_assets = []

        # Calculate overall market sentiment
        positive_changes = sum(1 for m in movers if m["change_24h"] > 0)
        total = len(movers)
        fear_greed = positive_changes / total if total > 0 else 0.5

        if fear_greed > 0.7:
            market_sentiment = "greedy"
        elif fear_greed < 0.3:
            market_sentiment = "fearful"
        else:
            market_sentiment = "neutral"

        return MarketOverview(
            generated_at=now,
            top_gainers=top_gainers,
            top_losers=top_losers,
            market_sentiment=market_sentiment,
            fear_greed_index=round(fear_greed * 100, 1),
            bullish_assets=bullish_assets,
            bearish_assets=bearish_assets,
            trending_topics=trending_topics,
            undervalued_assets=undervalued_assets,
            high_activity_assets=high_activity_assets,
        )

    async def compare_assets(
        self,
        slugs: list[str],
    ) -> dict:
        """
        Compare multiple assets side-by-side.

        Args:
            slugs: List of asset slugs to compare (max 5)

        Returns:
            Comparison data for all assets
        """
        if len(slugs) > 5:
            slugs = slugs[:5]

        reports = await asyncio.gather(
            *[self.get_asset_report(slug) for slug in slugs],
            return_exceptions=True,
        )

        comparisons = []
        for slug, report in zip(slugs, reports):
            if isinstance(report, Exception):
                comparisons.append({"asset": slug, "error": str(report)})
            else:
                comparisons.append(report.to_dict())

        # Determine winner by health score
        valid_reports = [r for r in reports if not isinstance(r, Exception)]
        winner = max(valid_reports, key=lambda r: r.health_score).slug if valid_reports else None

        return {
            "comparison": comparisons,
            "winner": winner,
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def screen_assets(
        self,
        preset: Optional[str] = None,
        custom_filters: Optional[list[dict]] = None,
    ) -> list[dict]:
        """
        Screen assets using presets or custom filters.

        Args:
            preset: Named preset (undervalued, oversold, etc.)
            custom_filters: Custom filter definitions

        Returns:
            List of assets passing the screen
        """
        if preset:
            results = await self._screener.quick_screen(preset)
        elif custom_filters:
            from .screener import ScreenerConfig, ScreenerFilter, FilterOperator

            filters = []
            for f in custom_filters:
                filters.append(ScreenerFilter(
                    metric=f["metric"],
                    operator=FilterOperator(f["operator"]),
                    value=f["value"],
                    value_max=f.get("value_max"),
                ))

            config = ScreenerConfig(filters=filters)
            results = await self._screener.screen(config)
        else:
            # Default: top by market cap
            results = await self._screener.screen(ScreenerConfig())

        return [r.to_dict() for r in results]

    # Expose individual product access
    @property
    def health_calculator(self) -> HealthScoreCalculator:
        return self._health_calculator

    @property
    def whale_tracker(self) -> WhaleTracker:
        return self._whale_tracker

    @property
    def signal_generator(self) -> SignalGenerator:
        return self._signal_generator

    @property
    def narrative_analyzer(self) -> NarrativeAnalyzer:
        return self._narrative_analyzer

    @property
    def screener(self) -> AssetScreener:
        return self._screener
