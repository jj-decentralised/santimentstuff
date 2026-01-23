"""
Data models for Nansen API responses.

These models represent the core data structures used throughout
the smart money dashboard.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# Keywords for holder categorization
FUND_KEYWORDS = [
    "fund", "capital", "ventures", "venture", "investment", "partners",
    "dao", "treasury", "foundation", "paradigm", "a16z", "polychain",
    "pantera", "multicoin", "dragonfly", "sequoia", "framework", "coinbase ventures",
    "binance labs", "jump", "wintermute", "alameda", "three arrows",
]

EXCHANGE_KEYWORDS = [
    "binance", "coinbase", "kraken", "okx", "huobi", "kucoin", "exchange",
    "deposit", "hot wallet", "ftx", "bybit", "bitfinex", "gemini", "bitstamp",
]


class SmartMoneyCategory(Enum):
    """Categories of smart money traders from Nansen."""
    ALL = "all"
    FUND = "Fund"
    SMART_TRADER = "Smart Trader"
    SMART_TRADER_30D = "30D Smart Trader"
    SMART_TRADER_90D = "90D Smart Trader"
    SMART_TRADER_180D = "180D Smart Trader"
    SMART_HL_PERPS = "Smart HL Perps Trader"


class Chain(Enum):
    """Supported blockchain networks."""
    ETHEREUM = "ethereum"
    SOLANA = "solana"
    ARBITRUM = "arbitrum"
    BASE = "base"
    BNB = "bnb"
    POLYGON = "polygon"
    OPTIMISM = "optimism"
    AVALANCHE = "avalanche"


# Valid values for API validation
VALID_CHAINS = [c.value for c in Chain]
VALID_CATEGORIES = [c.value for c in SmartMoneyCategory]


@dataclass
class TokenHolding:
    """Smart money token holding from /smart-money/holdings endpoint."""
    token_address: str
    token_symbol: str
    chain: str
    value_usd: float
    balance_24h_percent_change: float
    holders_count: int
    share_of_holdings_percent: float
    token_age_days: int
    market_cap_usd: float
    token_sectors: list[str] = field(default_factory=list)

    @classmethod
    def from_api_response(cls, data: dict) -> "TokenHolding":
        """Create from Nansen API response."""
        return cls(
            token_address=data.get("token_address", ""),
            token_symbol=data.get("token_symbol", ""),
            chain=data.get("chain", ""),
            value_usd=data.get("value_usd", 0.0),
            balance_24h_percent_change=data.get("balance_24h_percent_change", 0.0),
            holders_count=data.get("holders_count", 0),
            share_of_holdings_percent=data.get("share_of_holdings_percent", 0.0),
            token_age_days=data.get("token_age_days", 0),
            market_cap_usd=data.get("market_cap_usd", 0.0),
            token_sectors=data.get("token_sectors", []),
        )


@dataclass
class TokenNetflow:
    """Token netflow data from /smart-money/netflow endpoint."""
    token_address: str
    token_symbol: str
    chain: str
    net_flow_1h_usd: float
    net_flow_24h_usd: float
    net_flow_7d_usd: float
    net_flow_30d_usd: float
    trader_count_30d: int
    token_age_days: int
    market_cap_usd: float

    @property
    def is_accumulating(self) -> bool:
        """Check if token shows accumulation signal."""
        return self.net_flow_24h_usd > 0

    @property
    def is_distributing(self) -> bool:
        """Check if token shows distribution signal."""
        return self.net_flow_24h_usd < 0

    @classmethod
    def from_api_response(cls, data: dict) -> "TokenNetflow":
        """Create from Nansen API response."""
        return cls(
            token_address=data.get("token_address", ""),
            token_symbol=data.get("token_symbol", ""),
            chain=data.get("chain", ""),
            net_flow_1h_usd=data.get("net_flow_1h_usd", 0.0),
            net_flow_24h_usd=data.get("net_flow_24h_usd", 0.0),
            net_flow_7d_usd=data.get("net_flow_7d_usd", 0.0),
            net_flow_30d_usd=data.get("net_flow_30d_usd", 0.0),
            trader_count_30d=data.get("trader_count_30d", 0),
            token_age_days=data.get("token_age_days", 0),
            market_cap_usd=data.get("market_cap_usd", 0.0),
        )


@dataclass
class DexTrade:
    """Individual DEX trade from /smart-money/dex-trades endpoint."""
    chain: str
    block_timestamp: datetime
    transaction_hash: str
    trader_address: str
    trader_label: str
    token_bought_address: str
    token_sold_address: str
    token_bought_symbol: str
    token_sold_symbol: str
    token_bought_amount: float
    token_sold_amount: float
    trade_value_usd: float
    token_bought_age_days: int
    token_sold_age_days: int
    token_bought_market_cap: Optional[float]
    token_sold_market_cap: Optional[float]

    @property
    def is_buy(self) -> bool:
        """Determine if this is a buy (sold stablecoin/ETH for token)."""
        stables = {"USDC", "USDT", "DAI", "BUSD", "TUSD"}
        base_tokens = {"ETH", "WETH", "SOL", "BNB", "MATIC", "AVAX"}
        return self.token_sold_symbol in stables or self.token_sold_symbol in base_tokens

    @classmethod
    def from_api_response(cls, data: dict) -> "DexTrade":
        """Create from Nansen API response."""
        timestamp_str = data.get("block_timestamp", "")
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        else:
            timestamp = datetime.utcnow()

        return cls(
            chain=data.get("chain", ""),
            block_timestamp=timestamp,
            transaction_hash=data.get("transaction_hash", ""),
            trader_address=data.get("trader_address", ""),
            trader_label=data.get("trader_address_label", ""),
            token_bought_address=data.get("token_bought_address", ""),
            token_sold_address=data.get("token_sold_address", ""),
            token_bought_symbol=data.get("token_bought_symbol", ""),
            token_sold_symbol=data.get("token_sold_symbol", ""),
            token_bought_amount=data.get("token_bought_amount", 0.0),
            token_sold_amount=data.get("token_sold_amount", 0.0),
            trade_value_usd=data.get("trade_value_usd", 0.0),
            token_bought_age_days=data.get("token_bought_age_days", 0),
            token_sold_age_days=data.get("token_sold_age_days", 0),
            token_bought_market_cap=data.get("token_bought_market_cap"),
            token_sold_market_cap=data.get("token_sold_market_cap"),
        )


@dataclass
class TokenHolder:
    """Token holder from /tgm/holders endpoint."""
    address: str
    address_label: str
    token_amount: float
    total_inflow: float
    total_outflow: float
    balance_change_24h: float
    balance_change_7d: float
    balance_change_30d: float
    ownership_percentage: float
    value_usd: float

    @property
    def category(self) -> str:
        """Infer holder category from label (legacy - use holder_type instead)."""
        return self.holder_type

    @property
    def holder_type(self) -> str:
        """
        Categorize holder: fund, exchange, whale, smart_money, other.

        Uses keyword matching against address labels to identify
        institutional holders like venture funds and exchanges.
        """
        label_lower = self.address_label.lower()

        # Check for fund/VC keywords
        if any(kw in label_lower for kw in FUND_KEYWORDS):
            return "fund"

        # Check for exchange keywords
        if any(kw in label_lower for kw in EXCHANGE_KEYWORDS):
            return "exchange"

        # Size-based categorization
        if self.value_usd > 5_000_000:
            return "whale"
        elif self.value_usd > 500_000:
            return "smart_money"

        return "other"

    @property
    def net_tokens(self) -> float:
        """Net token position (inflow - outflow)."""
        return self.total_inflow - self.total_outflow

    @property
    def is_accumulating(self) -> bool:
        """Check if holder is accumulating based on recent balance changes."""
        return self.balance_change_24h > 0 or self.balance_change_7d > 0

    @property
    def is_distributing(self) -> bool:
        """Check if holder is distributing based on recent balance changes."""
        return self.balance_change_24h < 0 or self.balance_change_7d < 0

    @classmethod
    def from_api_response(cls, data: dict) -> "TokenHolder":
        """Create from Nansen API response."""
        return cls(
            address=data.get("address", ""),
            address_label=data.get("address_label", ""),
            token_amount=data.get("token_amount", 0.0),
            total_inflow=data.get("total_inflow", 0.0),
            total_outflow=data.get("total_outflow", 0.0),
            balance_change_24h=data.get("balance_change_24h", 0.0),
            balance_change_7d=data.get("balance_change_7d", 0.0),
            balance_change_30d=data.get("balance_change_30d", 0.0),
            ownership_percentage=data.get("ownership_percentage", 0.0),
            value_usd=data.get("value_usd", 0.0),
        )


@dataclass
class FlowIntelligence:
    """Flow intelligence from /tgm/flow-intelligence endpoint."""
    token_address: str
    chain: str
    # Public figures
    public_figure_net_flow_usd: float
    public_figure_wallet_count: int
    # Top PnL traders
    top_pnl_net_flow_usd: float
    top_pnl_wallet_count: int
    # Whales
    whale_net_flow_usd: float
    whale_wallet_count: int
    # Smart traders
    smart_trader_net_flow_usd: float
    smart_trader_wallet_count: int
    # Exchanges
    exchange_net_flow_usd: float
    exchange_wallet_count: int
    # Fresh wallets
    fresh_wallets_net_flow_usd: float
    fresh_wallets_wallet_count: int

    @classmethod
    def from_api_response(cls, data: dict, token_address: str, chain: str) -> "FlowIntelligence":
        """Create from Nansen API response."""
        # API returns data as a list with one item
        item = data[0] if isinstance(data, list) and data else data

        return cls(
            token_address=token_address,
            chain=chain,
            public_figure_net_flow_usd=item.get("public_figure_net_flow_usd", 0.0),
            public_figure_wallet_count=item.get("public_figure_wallet_count", 0),
            top_pnl_net_flow_usd=item.get("top_pnl_net_flow_usd", 0.0),
            top_pnl_wallet_count=item.get("top_pnl_wallet_count", 0),
            whale_net_flow_usd=item.get("whale_net_flow_usd", 0.0),
            whale_wallet_count=item.get("whale_wallet_count", 0),
            smart_trader_net_flow_usd=item.get("smart_trader_net_flow_usd", 0.0),
            smart_trader_wallet_count=item.get("smart_trader_wallet_count", 0),
            exchange_net_flow_usd=item.get("exchange_net_flow_usd", 0.0),
            exchange_wallet_count=item.get("exchange_wallet_count", 0),
            fresh_wallets_net_flow_usd=item.get("fresh_wallets_net_flow_usd", 0.0),
            fresh_wallets_wallet_count=item.get("fresh_wallets_wallet_count", 0),
        )

    def get_segment_flow(self, segment: str) -> tuple[float, int]:
        """Get net flow and wallet count for a segment."""
        mapping = {
            "public_figure": (self.public_figure_net_flow_usd, self.public_figure_wallet_count),
            "top_pnl": (self.top_pnl_net_flow_usd, self.top_pnl_wallet_count),
            "whale": (self.whale_net_flow_usd, self.whale_wallet_count),
            "smart_trader": (self.smart_trader_net_flow_usd, self.smart_trader_wallet_count),
            "exchange": (self.exchange_net_flow_usd, self.exchange_wallet_count),
            "fresh_wallets": (self.fresh_wallets_net_flow_usd, self.fresh_wallets_wallet_count),
        }
        return mapping.get(segment, (0.0, 0))
