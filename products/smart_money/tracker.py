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
    # Historical netflow data for sparklines
    net_flow_1h_usd: float = 0
    net_flow_7d_usd: float = 0
    net_flow_30d_usd: float = 0
    momentum: str = "steady"  # "accelerating", "decelerating", "steady"

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
            # Sparkline data
            "netflow_trend": [
                self.net_flow_1h_usd,
                self.net_flow_24h_usd,
                self.net_flow_7d_usd,
                self.net_flow_30d_usd,
            ],
            "momentum": self.momentum,
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
            momentum = self._calculate_momentum(nf) if nf else "steady"

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
                # Historical data for sparklines
                net_flow_1h_usd=nf.net_flow_1h_usd if nf else 0,
                net_flow_7d_usd=nf.net_flow_7d_usd if nf else 0,
                net_flow_30d_usd=nf.net_flow_30d_usd if nf else 0,
                momentum=momentum,
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
        # Fetch all TGM data in parallel with error handling
        holders_task = self.client.get_token_holders(token_address, chain)
        flows_task = self.client.get_flow_intelligence(token_address, chain)
        buyers_task = self.client.get_who_bought_sold(token_address, chain, "buy")
        sellers_task = self.client.get_who_bought_sold(token_address, chain, "sell")

        results = await asyncio.gather(
            holders_task, flows_task, buyers_task, sellers_task,
            return_exceptions=True
        )

        # Handle potential errors gracefully
        holders = results[0] if not isinstance(results[0], Exception) else []
        flows = results[1] if not isinstance(results[1], Exception) else None
        buyers = results[2] if not isinstance(results[2], Exception) else []
        sellers = results[3] if not isinstance(results[3], Exception) else []

        # Count holders by category
        holder_counts = self._count_holders_by_category(holders)

        # Get token symbol from first holder if available
        token_symbol = "UNKNOWN"
        if holders:
            # Try to infer from label or use address
            token_symbol = token_address[:8] + "..."

        # Generate narrative (handle missing flows)
        narrative = self.narrative_gen.generate_token_narrative(
            token_symbol, holders, flows, buyers, sellers
        )

        # Build flow intelligence response (handle None flows)
        flow_data = {
            "smart_money": {"net_flow_usd": 0, "wallet_count": 0},
            "whale": {"net_flow_usd": 0, "wallet_count": 0},
            "exchange": {"net_flow_usd": 0, "wallet_count": 0},
            "fresh_wallets": {"net_flow_usd": 0, "wallet_count": 0},
            "top_pnl": {"net_flow_usd": 0, "wallet_count": 0},
        }

        if flows:
            flow_data = {
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
            }

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
            "flow_intelligence": flow_data,
            "recent_buyers": buyers[:10] if buyers else [],
            "recent_sellers": sellers[:10] if sellers else [],
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

    def _calculate_momentum(self, netflow: TokenNetflow) -> str:
        """
        Calculate momentum based on netflow acceleration.

        Compares rate of change across time periods:
        - If 1h rate > 24h rate > 7d rate → accelerating
        - If 1h rate < 24h rate < 7d rate → decelerating
        - Otherwise → steady
        """
        # Normalize to daily rates for comparison
        rate_1h = netflow.net_flow_1h_usd * 24  # Annualize hourly rate
        rate_24h = netflow.net_flow_24h_usd
        rate_7d = netflow.net_flow_7d_usd / 7 if netflow.net_flow_7d_usd else 0

        # Check for acceleration (recent flows stronger than historical)
        if rate_1h > rate_24h > rate_7d and rate_24h > 0:
            return "accelerating"
        elif rate_1h < rate_24h < rate_7d and rate_24h < 0:
            return "accelerating"  # Accelerating distribution
        elif rate_1h < rate_24h < rate_7d and rate_24h > 0:
            return "decelerating"
        elif rate_1h > rate_24h > rate_7d and rate_24h < 0:
            return "decelerating"  # Decelerating distribution

        return "steady"

    def _calculate_velocity(
        self,
        balance_24h: float,
        balance_7d: float,
        balance_30d: float,
    ) -> dict:
        """
        Calculate holder velocity from balance changes.

        Returns velocity indicator and trend data.
        """
        # Normalize to daily rates
        rate_24h = balance_24h
        rate_7d = balance_7d / 7 if balance_7d else 0
        rate_30d = balance_30d / 30 if balance_30d else 0

        # Determine velocity
        if rate_24h > rate_7d > rate_30d:
            velocity = "accelerating"
        elif rate_24h < rate_7d < rate_30d:
            velocity = "decelerating"
        else:
            velocity = "steady"

        return {
            "indicator": velocity,
            "rate_24h": rate_24h,
            "rate_7d": rate_7d,
            "rate_30d": rate_30d,
            "trend": [balance_24h, balance_7d, balance_30d],
        }

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

    async def get_market_overview(
        self,
        chains: list[str],
    ) -> dict:
        """
        Get comprehensive market overview with aggregated stats.

        Returns data for charts and summary statistics.
        """
        # Fetch all data in parallel
        holdings_task = self.client.get_smart_money_holdings(chains, 100)
        netflow_task = self.client.get_smart_money_netflow(chains, 100)
        trades_task = self.client.get_dex_trades(chains, 100)

        results = await asyncio.gather(
            holdings_task, netflow_task, trades_task,
            return_exceptions=True
        )

        holdings = results[0] if not isinstance(results[0], Exception) else []
        netflows = results[1] if not isinstance(results[1], Exception) else []
        trades = results[2] if not isinstance(results[2], Exception) else []

        # Aggregate holdings stats
        total_value = sum(h.value_usd for h in holdings)
        total_holders = sum(h.holders_count for h in holdings)
        unique_tokens = len(set(h.token_address for h in holdings))

        # Aggregate netflow stats
        total_inflow = sum(n.net_flow_24h_usd for n in netflows if n.net_flow_24h_usd > 0)
        total_outflow = sum(n.net_flow_24h_usd for n in netflows if n.net_flow_24h_usd < 0)
        accumulating = sum(1 for n in netflows if n.is_accumulating)
        distributing = sum(1 for n in netflows if n.is_distributing)

        # Netflow time series data for charts
        netflow_chart_data = []
        for n in sorted(netflows, key=lambda x: x.net_flow_24h_usd, reverse=True)[:20]:
            netflow_chart_data.append({
                "token": n.token_symbol,
                "1h": n.net_flow_1h_usd,
                "24h": n.net_flow_24h_usd,
                "7d": n.net_flow_7d_usd,
                "30d": n.net_flow_30d_usd,
            })

        # Trade stats
        buy_count = sum(1 for t in trades if t.is_buy)
        sell_count = len(trades) - buy_count
        buy_volume = sum(t.trade_value_usd for t in trades if t.is_buy)
        sell_volume = sum(t.trade_value_usd for t in trades if not t.is_buy)

        # Top tokens by value
        top_by_value = sorted(holdings, key=lambda x: x.value_usd, reverse=True)[:10]

        # Top by inflow
        top_by_inflow = sorted(netflows, key=lambda x: x.net_flow_24h_usd, reverse=True)[:10]

        # Sector breakdown
        sector_counts = {}
        for h in holdings:
            for sector in h.token_sectors:
                sector_counts[sector] = sector_counts.get(sector, 0) + 1

        top_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:8]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "chains": chains,
            "summary": {
                "total_value_usd": total_value,
                "total_smart_money_holders": total_holders,
                "unique_tokens": unique_tokens,
                "tokens_accumulating": accumulating,
                "tokens_distributing": distributing,
                "net_flow_24h": total_inflow + total_outflow,
                "total_inflow_24h": total_inflow,
                "total_outflow_24h": total_outflow,
            },
            "trade_summary": {
                "total_trades": len(trades),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "buy_volume_usd": buy_volume,
                "sell_volume_usd": sell_volume,
                "buy_sell_ratio": buy_count / sell_count if sell_count > 0 else 0,
            },
            "charts": {
                "netflow_by_token": netflow_chart_data,
                "top_by_value": [
                    {"token": h.token_symbol, "value": h.value_usd, "holders": h.holders_count}
                    for h in top_by_value
                ],
                "top_by_inflow": [
                    {"token": n.token_symbol, "inflow": n.net_flow_24h_usd}
                    for n in top_by_inflow
                ],
                "sectors": [{"name": s[0], "count": s[1]} for s in top_sectors],
            },
        }

    async def get_perp_trades(
        self,
        limit: int = 50,
    ) -> dict:
        """
        Get perpetual trades from Hyperliquid.

        Returns formatted perp trade data.
        """
        try:
            trades = await self.client.get_perp_trades(limit)
        except Exception:
            trades = []

        formatted = []
        long_count = 0
        short_count = 0
        long_volume = 0
        short_volume = 0

        for t in trades:
            side = t.get("position_side", "").lower()
            value = t.get("value_usd", 0) or 0

            if side == "long":
                long_count += 1
                long_volume += value
            elif side == "short":
                short_count += 1
                short_volume += value

            formatted.append({
                "timestamp": t.get("block_timestamp", ""),
                "trader": t.get("trader_address_label", t.get("trader_address", "")[:10] + "..."),
                "token": t.get("token_symbol", ""),
                "side": side.upper() if side else "UNKNOWN",
                "action": t.get("action", ""),
                "value_usd": value,
                "price": t.get("price", 0),
            })

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_trades": len(formatted),
            "long_count": long_count,
            "short_count": short_count,
            "long_volume_usd": long_volume,
            "short_volume_usd": short_volume,
            "sentiment": "bullish" if long_count > short_count else "bearish" if short_count > long_count else "neutral",
            "trades": formatted,
        }

    # === Historical Data Methods ===

    async def get_token_history(
        self,
        chain: str,
        token_address: str,
        days: int = 30,
    ) -> dict:
        """
        Get historical smart money holdings for a token.

        Returns time-series data showing position building over time.
        """
        try:
            history = await self.client.get_historical_holdings(token_address, chain, days)
        except Exception:
            history = []

        # Format for chart
        chart_data = []
        for h in history:
            chart_data.append({
                "date": h.get("date", ""),
                "value_usd": h.get("value_usd", 0),
                "balance": h.get("balance", 0),
                "holder_count": h.get("holder_count", 0),
            })

        # Calculate key metrics
        if len(chart_data) >= 2:
            first_value = chart_data[0].get("value_usd", 0)
            last_value = chart_data[-1].get("value_usd", 0)
            change_pct = ((last_value - first_value) / first_value * 100) if first_value else 0

            # Find peak and trough
            values = [d.get("value_usd", 0) for d in chart_data]
            peak_value = max(values) if values else 0
            trough_value = min(values) if values else 0
            peak_date = chart_data[values.index(peak_value)].get("date") if peak_value else None
        else:
            change_pct = 0
            peak_value = 0
            trough_value = 0
            peak_date = None

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "chain": chain,
            "token_address": token_address,
            "days": days,
            "data_points": len(chart_data),
            "chart_data": chart_data,
            "metrics": {
                "period_change_pct": change_pct,
                "peak_value_usd": peak_value,
                "peak_date": peak_date,
                "trough_value_usd": trough_value,
                "trend": "accumulating" if change_pct > 10 else "distributing" if change_pct < -10 else "stable",
            },
        }

    async def get_token_transfers(
        self,
        chain: str,
        token_address: str,
        days: int = 7,
    ) -> dict:
        """
        Get token transfer activity by smart money.

        Returns flow analysis: CEX deposits (exit signals) vs DEX activity.
        """
        try:
            transfers = await self.client.get_token_transfers(token_address, chain, days)
        except Exception:
            transfers = []

        # Categorize transfers
        cex_deposits = []
        cex_withdrawals = []
        dex_swaps = []
        wallet_transfers = []

        cex_deposit_volume = 0
        cex_withdrawal_volume = 0
        dex_volume = 0
        wallet_volume = 0

        for t in transfers:
            transfer_type = t.get("transfer_type", "").lower()
            value = t.get("value_usd", 0) or 0

            transfer_item = {
                "timestamp": t.get("timestamp", ""),
                "from_address": t.get("from_address", ""),
                "from_label": t.get("from_label", ""),
                "to_address": t.get("to_address", ""),
                "to_label": t.get("to_label", ""),
                "value_usd": value,
                "type": transfer_type,
            }

            if "cex" in transfer_type and "deposit" in transfer_type:
                cex_deposits.append(transfer_item)
                cex_deposit_volume += value
            elif "cex" in transfer_type and "withdrawal" in transfer_type:
                cex_withdrawals.append(transfer_item)
                cex_withdrawal_volume += value
            elif "dex" in transfer_type or "swap" in transfer_type:
                dex_swaps.append(transfer_item)
                dex_volume += value
            else:
                wallet_transfers.append(transfer_item)
                wallet_volume += value

        # Determine flow sentiment
        net_cex_flow = cex_deposit_volume - cex_withdrawal_volume
        if net_cex_flow > 100_000:
            flow_sentiment = "bearish"  # Net deposits to CEX = sell pressure
            flow_signal = "CEX deposits high - potential sell pressure"
        elif net_cex_flow < -100_000:
            flow_sentiment = "bullish"  # Net withdrawals from CEX = accumulation
            flow_signal = "CEX withdrawals high - accumulation signal"
        else:
            flow_sentiment = "neutral"
            flow_signal = "Balanced CEX flows"

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "chain": chain,
            "token_address": token_address,
            "days": days,
            "total_transfers": len(transfers),
            "summary": {
                "cex_deposit_volume": cex_deposit_volume,
                "cex_withdrawal_volume": cex_withdrawal_volume,
                "net_cex_flow": net_cex_flow,
                "dex_volume": dex_volume,
                "wallet_volume": wallet_volume,
                "flow_sentiment": flow_sentiment,
                "flow_signal": flow_signal,
            },
            "flow_breakdown": {
                "cex_deposits": cex_deposits[:10],
                "cex_withdrawals": cex_withdrawals[:10],
                "dex_swaps": dex_swaps[:10],
                "wallet_transfers": wallet_transfers[:10],
            },
        }
