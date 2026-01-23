"""Data models for Arkham Intelligence API responses."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Fund:
    """Represents a fund/entity in Arkham."""
    id: str
    name: str
    type: str
    website: str | None = None
    twitter: str | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict) -> "Fund":
        tags = []
        for tag in data.get("populatedTags", []):
            label = tag.get("label", "")
            if not label.startswith("{"):  # Skip JSON-encoded tags
                tags.append(label)
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            type=data.get("type", "unknown"),
            website=data.get("website"),
            twitter=data.get("twitter"),
            tags=tags[:10],  # Limit tags
        )


@dataclass
class TokenHolding:
    """A single token holding."""
    token_id: str
    name: str
    symbol: str
    chain: str
    balance: float
    price: float
    value_usd: float

    @classmethod
    def from_api(cls, chain: str, token_id: str, data: dict) -> "TokenHolding":
        return cls(
            token_id=token_id,
            name=data.get("name", "Unknown"),
            symbol=data.get("symbol", "???").upper(),
            chain=chain,
            balance=data.get("balance", 0),
            price=data.get("price", 0),
            value_usd=data.get("usd", 0),
        )


@dataclass
class Transfer:
    """A single transfer transaction."""
    id: str
    tx_hash: str
    timestamp: datetime
    token_symbol: str
    token_name: str
    token_address: str
    chain: str
    amount: float
    historical_usd: float
    direction: str  # "in" or "out"
    counterparty: str | None = None
    counterparty_entity: str | None = None

    @classmethod
    def from_api(cls, data: dict, entity_id: str) -> "Transfer":
        # Determine direction based on entity match
        to_entity = data.get("toAddress", {}).get("arkhamEntity", {})
        from_entity = data.get("fromAddress", {}).get("arkhamEntity", {})

        if to_entity.get("id") == entity_id:
            direction = "in"
            counterparty_addr = data.get("fromAddress", {})
        else:
            direction = "out"
            counterparty_addr = data.get("toAddress", {})

        counterparty = counterparty_addr.get("address")
        counterparty_entity_data = counterparty_addr.get("arkhamEntity", {})
        counterparty_entity = counterparty_entity_data.get("name") if counterparty_entity_data else None

        # Parse timestamp
        ts_str = data.get("blockTimestamp", "")
        try:
            timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except:
            timestamp = datetime.now()

        # Handle None values explicitly
        token_symbol = data.get("tokenSymbol") or "???"
        token_name = data.get("tokenName") or "Unknown"
        token_address = data.get("tokenAddress") or ""
        chain = data.get("chain") or "unknown"
        amount = data.get("unitValue") or 0
        historical_usd = data.get("historicalUSD") or 0

        return cls(
            id=data.get("id", ""),
            tx_hash=data.get("transactionHash", ""),
            timestamp=timestamp,
            token_symbol=token_symbol.upper(),
            token_name=token_name,
            token_address=token_address,
            chain=chain,
            amount=amount,
            historical_usd=historical_usd,
            direction=direction,
            counterparty=counterparty,
            counterparty_entity=counterparty_entity,
        )


@dataclass
class FlowDataPoint:
    """A single flow data point."""
    timestamp: datetime
    inflow: float
    outflow: float
    cumulative_inflow: float
    cumulative_outflow: float

    @classmethod
    def from_api(cls, data: dict) -> "FlowDataPoint":
        ts_str = data.get("time", "")
        try:
            timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except:
            timestamp = datetime.now()
        return cls(
            timestamp=timestamp,
            inflow=data.get("inflow", 0),
            outflow=data.get("outflow", 0),
            cumulative_inflow=data.get("cumulativeInflow", 0),
            cumulative_outflow=data.get("cumulativeOutflow", 0),
        )


@dataclass
class FlowData:
    """Flow data for an entity by chain."""
    chain: str
    data_points: list[FlowDataPoint]

    @property
    def total_inflow(self) -> float:
        if not self.data_points:
            return 0
        return self.data_points[-1].cumulative_inflow

    @property
    def total_outflow(self) -> float:
        if not self.data_points:
            return 0
        return self.data_points[-1].cumulative_outflow

    @property
    def net_flow(self) -> float:
        return self.total_inflow - self.total_outflow


@dataclass
class CostBasis:
    """Cost basis for a token position."""
    token_id: str
    symbol: str
    total_acquired: float
    total_cost_usd: float
    total_disposed: float
    total_proceeds_usd: float
    current_balance: float
    avg_cost_per_unit: float

    @property
    def total_invested(self) -> float:
        """Net cost basis (cost - proceeds from sales)."""
        return self.total_cost_usd - self.total_proceeds_usd


@dataclass
class PnLSummary:
    """P/L summary for a position."""
    token_id: str
    symbol: str
    current_value: float
    cost_basis: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    realized_pnl: float


@dataclass
class Portfolio:
    """Complete portfolio for a fund."""
    fund: Fund
    holdings: list[TokenHolding]
    total_value_usd: float
    cost_basis_by_token: dict[str, CostBasis]
    pnl_summary: list[PnLSummary]

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.pnl_summary)

    @property
    def total_cost_basis(self) -> float:
        return sum(cb.total_invested for cb in self.cost_basis_by_token.values())

    @property
    def total_pnl_pct(self) -> float:
        if self.total_cost_basis == 0:
            return 0
        return (self.total_unrealized_pnl / self.total_cost_basis) * 100
