"""
Smart Money Tracker.

Core business logic for tracking smart money activity
and aggregating data from Nansen API.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from core.nansen_client import NansenClient
from core.nansen_models import (
    TokenHolding,
    TokenNetflow,
    DexTrade,
    TokenHolder,
    FlowIntelligence,
)
from .narrative import SmartMoneyNarrativeGenerator


@dataclass
class TokenPurchaseItem:
    """Token in the purchases overview."""
    token_symbol: str
    token_address: str
    chain: str
    smart_money_holders: int
    net_flow_24h_usd: float
    total_value_usd: float
    market_cap_usd: float
    signal: str  # "accumulating", "distributing", "neutral"
    signal_strength: str  # "strong", "moderate", "weak"
    sectors: list[str]

    def to_dict(self) -> dict:
        return {
            "token_symbol": self.token_symbol,
            "token_address": self.token_address,
            "chain": self.chain,
            "smart_money_holders": self.smart_money_holders,
            "net_flow_24h_usd": self.net_flow_24h_usd,
            "total_value_usd": self.total_value_usd,
            "market_cap_usd": self.market_cap_usd,
            "signal": self.signal,
            "signal_strength": self.signal_strength,
            "sectors": self.sectors,
        }


@dataclass
class DexTradeItem:
    """Formatted DEX trade."""
    timestamp: str
    wallet_label: str
    action: str
    token_bought: str
    token_sold: str
    amount_usd: float
    chain: str
    tx_hash: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "wallet_label": self.wallet_label,
            "action": self.action,
            "token_bought": self.token_bought,
            "token_sold": self.token_sold,
            "amount_usd": self.amount_usd,
            "chain": self.chain,
            "tx_hash": self.tx_hash,
        }


class SmartMoneyTracker:
    """
    Core logic for tracking smart money activity.
    Aggregates data from Nansen API and generates insights.
    """

    def __init__(self, client: NansenClient):
        self.client = client
        self.narrative_gen = SmartMoneyNarrativeGenerator()

    async def get_token_purchases(
        self,
        chains: list[str],
        sort_by: str = "net_flow_24h_usd",
        limit: int = 50,
    ) -> dict:
        """
        Get overview of tokens being purchased by smart money.

        Args:
            chains: Blockchain networks to query
            sort_by: Field to sort by
            limit: Maximum results

        Returns:
            Token purchases response dict
        """
        # Fetch holdings and netflow in parallel
        holdings_task = self.client.get_smart_money_holdings(chains, limit * 2)
        netflow_task = self.client.get_smart_money_netflow(chains, limit * 2)

        holdings, netflows = await asyncio.gather(holdings_task, netflow_task)

        # Create netflow lookup by token address
        netflow_map = {nf.token_address: nf for nf in netflows}

        # Merge data
        tokens = []
        for h in holdings:
            nf = netflow_map.get(h.token_address)
            signal, strength = self._calculate_signal(h, nf)

            tokens.append(TokenPurchaseItem(
                token_symbol=h.token_symbol,
                token_address=h.token_address,
                chain=h.chain,
                smart_money_holders=h.holders_count,
                net_flow_24h_usd=nf.net_flow_24h_usd if nf else 0,
                total_value_usd=h.value_usd,
                market_cap_usd=h.market_cap_usd,
                signal=signal,
                signal_strength=strength,
                sectors=h.token_sectors,
            ))

        # Sort
        if sort_by == "net_flow_24h_usd":
            tokens.sort(key=lambda x: x.net_flow_24h_usd, reverse=True)
        elif sort_by == "total_value_usd":
            tokens.sort(key=lambda x: x.total_value_usd, reverse=True)
        elif sort_by == "smart_money_holders":
            tokens.sort(key=lambda x: x.smart_money_holders, reverse=True)

        # Count signals
        accumulating = sum(1 for t in tokens if t.signal == "accumulating")
        distributing = sum(1 for t in tokens if t.signal == "distributing")

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "chains": chains,
            "total_tokens": len(tokens),
            "accumulating_count": accumulating,
            "distributing_count": distributing,
            "tokens": [t.to_dict() for t in tokens[:limit]],
        }

    async def get_recent_trades(
        self,
        chains: list[str],
        limit: int = 50,
    ) -> dict:
        """
        Get recent DEX trades by smart money.

        Args:
            chains: Blockchain networks
            limit: Maximum results

        Returns:
            Trades response dict
        """
        trades = await self.client.get_dex_trades(chains, limit)

        formatted_trades = []
        for t in trades:
            action = "BUY" if t.is_buy else "SELL"
            formatted_trades.append(DexTradeItem(
                timestamp=t.block_timestamp.isoformat(),
                wallet_label=t.trader_label or t.trader_address[:10] + "...",
                action=action,
                token_bought=t.token_bought_symbol,
                token_sold=t.token_sold_symbol,
                amount_usd=t.trade_value_usd,
                chain=t.chain,
                tx_hash=t.transaction_hash,
            ))

        # Generate narrative
        buy_count = sum(1 for t in formatted_trades if t.action == "BUY")
        sell_count = len(formatted_trades) - buy_count
        buy_vol = sum(t.amount_usd for t in formatted_trades if t.action == "BUY")
        sell_vol = sum(t.amount_usd for t in formatted_trades if t.action == "SELL")

        narrative = self.narrative_gen.generate_trades_narrative(
            buy_count, sell_count, buy_vol, sell_vol
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "chains": chains,
            "total_trades": len(formatted_trades),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "buy_volume_usd": buy_vol,
            "sell_volume_usd": sell_vol,
            "narrative": narrative,
            "trades": [t.to_dict() for t in formatted_trades],
        }

    async def get_token_drilldown(
        self,
        chain: str,
        token_address: str,
    ) -> dict:
        """
        Get detailed holder activity for a token.

        Args:
            chain: Blockchain network
            token_address: Token contract address

        Returns:
            Token drilldown response dict
        """
        # Fetch all TGM data in parallel
        holders_task = self.client.get_token_holders(token_address, chain)
        flows_task = self.client.get_flow_intelligence(token_address, chain)
        buyers_task = self.client.get_who_bought_sold(token_address, chain, "buy")
        sellers_task = self.client.get_who_bought_sold(token_address, chain, "sell")

        holders, flows, buyers, sellers = await asyncio.gather(
            holders_task, flows_task, buyers_task, sellers_task
        )

        # Count holders by category
        holder_counts = self._count_holders_by_category(holders)

        # Get token symbol from first holder if available
        token_symbol = "UNKNOWN"
        if holders:
            # Try to infer from label or use address
            token_symbol = token_address[:8] + "..."

        # Generate narrative
        narrative = self.narrative_gen.generate_token_narrative(
            token_symbol, holders, flows, buyers, sellers
        )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "chain": chain,
            "token_address": token_address,
            "token_symbol": token_symbol,
            "holder_breakdown": {
                "total": len(holders),
                "smart_money": holder_counts.get("smart_money", 0),
                "whale": holder_counts.get("whale", 0),
                "exchange": holder_counts.get("exchange", 0),
                "other": holder_counts.get("other", 0),
            },
            "flow_intelligence": {
                "smart_money": {
                    "net_flow_usd": flows.smart_trader_net_flow_usd,
                    "wallet_count": flows.smart_trader_wallet_count,
                },
                "whale": {
                    "net_flow_usd": flows.whale_net_flow_usd,
                    "wallet_count": flows.whale_wallet_count,
                },
                "exchange": {
                    "net_flow_usd": flows.exchange_net_flow_usd,
                    "wallet_count": flows.exchange_wallet_count,
                },
                "fresh_wallets": {
                    "net_flow_usd": flows.fresh_wallets_net_flow_usd,
                    "wallet_count": flows.fresh_wallets_wallet_count,
                },
                "top_pnl": {
                    "net_flow_usd": flows.top_pnl_net_flow_usd,
                    "wallet_count": flows.top_pnl_wallet_count,
                },
            },
            "recent_buyers": buyers[:10],
            "recent_sellers": sellers[:10],
            "top_holders": [
                {
                    "address": h.address,
                    "label": h.address_label,
                    "value_usd": h.value_usd,
                    "ownership_pct": h.ownership_percentage,
                    "balance_change_24h": h.balance_change_24h,
                }
                for h in holders[:10]
            ],
            "narrative": narrative,
        }

    def _calculate_signal(
        self,
        holding: TokenHolding,
        netflow: Optional[TokenNetflow],
    ) -> tuple[str, str]:
        """Calculate accumulation/distribution signal."""
        if not netflow:
            return "neutral", "weak"

        flow = netflow.net_flow_24h_usd

        if flow > 0:
            if flow > 500_000:
                return "accumulating", "strong"
            elif flow > 100_000:
                return "accumulating", "moderate"
            else:
                return "accumulating", "weak"
        elif flow < 0:
            if flow < -500_000:
                return "distributing", "strong"
            elif flow < -100_000:
                return "distributing", "moderate"
            else:
                return "distributing", "weak"

        return "neutral", "weak"

    def _count_holders_by_category(
        self,
        holders: list[TokenHolder],
    ) -> dict[str, int]:
        """Count holders by category."""
        counts = {
            "smart_money": 0,
            "whale": 0,
            "exchange": 0,
            "other": 0,
        }

        for h in holders:
            category = h.category
            if category in counts:
                counts[category] += 1
            else:
                counts["other"] += 1

        return counts
