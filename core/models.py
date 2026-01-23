"""
Core data models for the Santiment Platform.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class HolderLabel(Enum):
    """Labels for categorizing wallet holders."""
    EXCHANGE = "exchange"
    WHALE = "whale"
    MINER = "miner"
    INFRASTRUCTURE = "infrastructure"
    DEX_TRADER = "dex_trader"
    DEFI = "defi"
    UNKNOWN = "unknown"


class SentimentLevel(Enum):
    """Sentiment classification levels."""
    EXTREME_FEAR = "extreme_fear"
    FEAR = "fear"
    NEUTRAL = "neutral"
    GREED = "greed"
    EXTREME_GREED = "extreme_greed"


class MarketCyclePhase(Enum):
    """Market cycle phases based on composite indicators."""
    ACCUMULATION = "accumulation"
    MARKUP = "markup"
    DISTRIBUTION = "distribution"
    MARKDOWN = "markdown"


@dataclass
class Asset:
    """Represents a cryptocurrency asset."""
    slug: str
    name: str
    ticker: str
    market_cap_usd: Optional[float] = None
    price_usd: Optional[float] = None
    infrastructure: Optional[str] = None  # e.g., "ETH", "BTC"

    def __hash__(self):
        return hash(self.slug)


@dataclass
class Metric:
    """Represents a Santiment metric."""
    name: str
    description: str
    min_interval: str = "1d"
    default_aggregation: str = "AVG"
    available_since: Optional[datetime] = None
    is_restricted: bool = False


@dataclass
class TimeseriesData:
    """Generic timeseries data point."""
    datetime: datetime
    value: float
    metric: str
    asset_slug: str


@dataclass
class WhaleTransaction:
    """Represents a large transaction by a whale wallet."""
    datetime: datetime
    asset_slug: str
    from_address: str
    to_address: str
    value: float
    value_usd: float
    tx_hash: str
    from_label: HolderLabel = HolderLabel.UNKNOWN
    to_label: HolderLabel = HolderLabel.UNKNOWN
    is_exchange_deposit: bool = False
    is_exchange_withdrawal: bool = False

    @property
    def is_exchange_flow(self) -> bool:
        return self.is_exchange_deposit or self.is_exchange_withdrawal


@dataclass
class ExchangeFlow:
    """Aggregated exchange flow data."""
    datetime: datetime
    asset_slug: str
    inflow: float
    outflow: float
    net_flow: float
    exchange: Optional[str] = None  # None = all exchanges

    @property
    def is_bearish_signal(self) -> bool:
        """Net positive flow to exchanges often precedes selling."""
        return self.net_flow > 0


@dataclass
class HolderDistribution:
    """Token holder distribution by balance tier."""
    asset_slug: str
    datetime: datetime
    tier: str  # e.g., "1-10", "10-100", "100k-1m"
    holder_count: int
    total_balance: float
    percent_of_supply: float


@dataclass
class SentimentData:
    """Social sentiment data for an asset."""
    datetime: datetime
    asset_slug: str
    sentiment_score: float  # -1 to 1
    sentiment_weighted: float
    social_volume: int
    social_dominance: float
    positive_mentions: int
    negative_mentions: int

    @property
    def sentiment_level(self) -> SentimentLevel:
        if self.sentiment_weighted < -0.5:
            return SentimentLevel.EXTREME_FEAR
        elif self.sentiment_weighted < -0.2:
            return SentimentLevel.FEAR
        elif self.sentiment_weighted < 0.2:
            return SentimentLevel.NEUTRAL
        elif self.sentiment_weighted < 0.5:
            return SentimentLevel.GREED
        else:
            return SentimentLevel.EXTREME_GREED


@dataclass
class TrendingWord:
    """A trending word/topic in crypto social media."""
    word: str
    hype_score: float
    social_volume: int
    unique_authors: int
    hour: datetime
    context: str = ""  # What assets/topics it relates to


@dataclass
class DevActivity:
    """Development activity metrics for a project."""
    datetime: datetime
    asset_slug: str
    dev_activity: float  # Weighted GitHub activity
    dev_activity_contributors: int
    github_activity: float  # Raw GitHub events
    contributors_count: int


@dataclass
class ValuationMetrics:
    """On-chain valuation metrics."""
    datetime: datetime
    asset_slug: str
    mvrv_ratio: float
    mvrv_long_short_diff: Optional[float] = None
    nvt_ratio: Optional[float] = None
    realized_cap: Optional[float] = None
    market_cap: Optional[float] = None

    @property
    def is_undervalued(self) -> bool:
        """MVRV < 1 suggests undervaluation."""
        return self.mvrv_ratio < 1.0

    @property
    def is_overvalued(self) -> bool:
        """MVRV > 3.5 historically signals tops."""
        return self.mvrv_ratio > 3.5


@dataclass
class NetworkMetrics:
    """On-chain network activity metrics."""
    datetime: datetime
    asset_slug: str
    daily_active_addresses: int
    network_growth: int  # New addresses
    transaction_volume: float
    velocity: float
    token_age_consumed: float
    realized_profit_loss: Optional[float] = None


@dataclass
class HealthScore:
    """Composite health score for a project (0-100)."""
    asset_slug: str
    computed_at: datetime
    overall_score: float

    # Component scores (0-100)
    dev_activity_score: float
    holder_distribution_score: float
    social_momentum_score: float
    onchain_usage_score: float
    valuation_score: float

    # Raw data used
    dev_activity_trend: float  # % change
    whale_concentration: float  # % held by top 100
    social_volume_change: float  # % change
    daa_change: float  # % change in daily active addresses
    mvrv_position: float

    # Flags
    red_flags: list[str] = field(default_factory=list)
    green_flags: list[str] = field(default_factory=list)

    @property
    def grade(self) -> str:
        if self.overall_score >= 80:
            return "A"
        elif self.overall_score >= 60:
            return "B"
        elif self.overall_score >= 40:
            return "C"
        elif self.overall_score >= 20:
            return "D"
        else:
            return "F"


@dataclass
class NarrativeInsight:
    """AI-generated market narrative insight."""
    datetime: datetime
    asset_slug: Optional[str]  # None for market-wide
    narrative: str  # Human-readable narrative
    key_drivers: list[str]
    sentiment_alignment: bool  # Does price align with sentiment?
    trending_topics: list[TrendingWord]
    confidence_score: float  # 0-1

    # Supporting data
    price_change_24h: float
    social_volume_change: float
    whale_activity_summary: str


@dataclass
class TradingSignal:
    """Trading signal from sentiment analysis."""
    datetime: datetime
    asset_slug: str
    signal_type: str  # "BUY", "SELL", "HOLD"
    strength: float  # 0-1
    reason: str

    # Supporting metrics
    sentiment_score: float
    social_volume: int
    price_at_signal: float

    # Risk management
    suggested_stop_loss: Optional[float] = None
    suggested_take_profit: Optional[float] = None

    @property
    def is_actionable(self) -> bool:
        return self.strength >= 0.6 and self.signal_type != "HOLD"


@dataclass
class Alert:
    """Generic alert for any product."""
    id: str
    created_at: datetime
    alert_type: str
    asset_slug: Optional[str]
    title: str
    message: str
    severity: str  # "low", "medium", "high", "critical"
    data: dict = field(default_factory=dict)
    is_read: bool = False
