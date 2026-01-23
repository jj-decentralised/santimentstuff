"""
Smart Money Narrative Generator.

Generates human-readable narratives from smart money data
using intelligent templates. No LLM dependencies.
"""

from typing import Optional

from core.nansen_models import TokenHolder, FlowIntelligence


class SmartMoneyNarrativeGenerator:
    """
    Generates human-readable narratives from smart money data.
    Uses intelligent templates - no LLM dependencies.
    """

    def generate_purchases_narrative(
        self,
        total_tokens: int,
        accumulating: int,
        distributing: int,
        top_tokens: list[str],
        total_value: float,
    ) -> str:
        """Generate narrative for token purchases overview."""

        # Opening statement
        if accumulating > distributing * 2:
            sentiment = "Strong accumulation signals across the market"
        elif distributing > accumulating * 2:
            sentiment = "Distribution signals dominate the market"
        elif accumulating > distributing:
            sentiment = "Mild accumulation bias in smart money activity"
        elif distributing > accumulating:
            sentiment = "Slight distribution tendency observed"
        else:
            sentiment = "Balanced activity with no clear directional bias"

        # Top tokens
        tokens_str = ", ".join(top_tokens[:5]) if top_tokens else "various tokens"

        # Value context
        if total_value > 1_000_000_000:
            value_str = f"${total_value / 1_000_000_000:.1f}B"
        elif total_value > 1_000_000:
            value_str = f"${total_value / 1_000_000:.1f}M"
        else:
            value_str = f"${total_value / 1_000:.0f}K"

        return f"""{sentiment}. Tracking {total_tokens} tokens with {accumulating} showing net inflows and {distributing} with outflows. Top positions include {tokens_str}. Total tracked value: {value_str}."""

    def generate_trades_narrative(
        self,
        buy_count: int,
        sell_count: int,
        buy_volume: float,
        sell_volume: float,
    ) -> str:
        """Generate narrative for recent trades."""

        total_trades = buy_count + sell_count
        if total_trades == 0:
            return "No recent trading activity recorded."

        buy_ratio = buy_count / total_trades
        vol_ratio = buy_volume / (buy_volume + sell_volume) if (buy_volume + sell_volume) > 0 else 0.5

        # Format volumes
        def fmt_vol(v: float) -> str:
            if v >= 1_000_000:
                return f"${v / 1_000_000:.1f}M"
            elif v >= 1_000:
                return f"${v / 1_000:.0f}K"
            else:
                return f"${v:.0f}"

        buy_vol_str = fmt_vol(buy_volume)
        sell_vol_str = fmt_vol(sell_volume)

        if buy_ratio > 0.65 and vol_ratio > 0.6:
            return f"Bullish trading pattern with {buy_count} buys vs {sell_count} sells. Buy volume ({buy_vol_str}) significantly exceeds sell volume ({sell_vol_str}), indicating strong accumulation."
        elif buy_ratio < 0.35 and vol_ratio < 0.4:
            return f"Bearish trading pattern with {sell_count} sells vs {buy_count} buys. Sell volume ({sell_vol_str}) dominates buy volume ({buy_vol_str}), suggesting distribution."
        elif buy_ratio > 0.55:
            return f"Slight buying bias with {buy_count} buys and {sell_count} sells. Volume: {buy_vol_str} bought, {sell_vol_str} sold."
        elif buy_ratio < 0.45:
            return f"Slight selling bias with {sell_count} sells and {buy_count} buys. Volume: {sell_vol_str} sold, {buy_vol_str} bought."
        else:
            return f"Mixed trading activity with {buy_count} buys ({buy_vol_str}) and {sell_count} sells ({sell_vol_str}). No clear directional bias."

    def generate_token_narrative(
        self,
        token_symbol: str,
        holders: list[TokenHolder],
        flows: FlowIntelligence,
        buyers: list[dict],
        sellers: list[dict],
    ) -> str:
        """Generate narrative for token drilldown view."""

        sections = []

        # Holder breakdown
        holder_text = self._holder_breakdown_narrative(holders)
        sections.append(f"**Holder Analysis:** {holder_text}")

        # Flow intelligence
        flow_text = self._flow_intelligence_narrative(flows)
        sections.append(f"**Flow Intelligence:** {flow_text}")

        # Recent activity
        activity_text = self._buyer_seller_narrative(len(buyers), len(sellers))
        sections.append(f"**Recent Activity:** {activity_text}")

        return "\n\n".join(sections)

    def _holder_breakdown_narrative(self, holders: list[TokenHolder]) -> str:
        """Generate holder breakdown narrative."""
        total = len(holders)
        if total == 0:
            return "No holder data available."

        # Count categories
        smart_money = sum(1 for h in holders if h.category == "smart_money")
        whales = sum(1 for h in holders if h.category == "whale")
        exchanges = sum(1 for h in holders if h.category == "exchange")

        sm_pct = (smart_money / total * 100) if total > 0 else 0
        whale_pct = (whales / total * 100) if total > 0 else 0

        # Total value
        total_value = sum(h.value_usd for h in holders)
        if total_value >= 1_000_000_000:
            value_str = f"${total_value / 1_000_000_000:.1f}B"
        elif total_value >= 1_000_000:
            value_str = f"${total_value / 1_000_000:.1f}M"
        else:
            value_str = f"${total_value / 1_000:.0f}K"

        if sm_pct > 15:
            return f"High institutional interest with {smart_money} smart money holders ({sm_pct:.1f}% of top {total}). {whales} whale addresses and {exchanges} exchange wallets tracked. Total value: {value_str}."
        elif sm_pct > 5:
            return f"Moderate smart money presence with {smart_money} labeled addresses ({sm_pct:.1f}%). {whales} whales and {exchanges} exchanges among top {total} holders. Total value: {value_str}."
        else:
            return f"Limited institutional presence with {smart_money} smart money holders among top {total}. {whales} whale addresses hold significant positions. Total tracked value: {value_str}."

    def _flow_intelligence_narrative(self, flows: FlowIntelligence) -> str:
        """Generate flow intelligence narrative."""

        def fmt_flow(v: float) -> str:
            prefix = "+" if v > 0 else ""
            if abs(v) >= 1_000_000:
                return f"{prefix}${v / 1_000_000:.1f}M"
            elif abs(v) >= 1_000:
                return f"{prefix}${v / 1_000:.0f}K"
            else:
                return f"{prefix}${v:.0f}"

        sm_flow = flows.smart_trader_net_flow_usd
        whale_flow = flows.whale_net_flow_usd
        exchange_flow = flows.exchange_net_flow_usd
        fresh_flow = flows.fresh_wallets_net_flow_usd

        parts = []

        # Smart money
        if sm_flow > 10_000:
            parts.append(f"Smart money accumulating ({fmt_flow(sm_flow)})")
        elif sm_flow < -10_000:
            parts.append(f"Smart money distributing ({fmt_flow(sm_flow)})")

        # Whales
        if whale_flow > 50_000:
            parts.append(f"whale accumulation ({fmt_flow(whale_flow)})")
        elif whale_flow < -50_000:
            parts.append(f"whale distribution ({fmt_flow(whale_flow)})")

        # Exchange flows (negative = bullish as tokens leave exchanges)
        if exchange_flow < -100_000:
            parts.append(f"tokens leaving exchanges ({fmt_flow(exchange_flow)}) - bullish")
        elif exchange_flow > 100_000:
            parts.append(f"tokens entering exchanges ({fmt_flow(exchange_flow)}) - bearish")

        # Fresh wallets
        if fresh_flow > 50_000:
            parts.append(f"new wallet inflows ({fmt_flow(fresh_flow)})")

        if parts:
            return " ".join(parts) + "."
        else:
            return "No significant flow activity detected in recent period."

    def _buyer_seller_narrative(self, buyer_count: int, seller_count: int) -> str:
        """Generate buyer/seller narrative."""

        if buyer_count == 0 and seller_count == 0:
            return "No recent buyer/seller data available."

        total = buyer_count + seller_count
        if buyer_count > seller_count * 1.5:
            return f"Net buying pressure with {buyer_count} identified buyers vs {seller_count} sellers in recent activity."
        elif seller_count > buyer_count * 1.5:
            return f"Net selling pressure with {seller_count} identified sellers vs {buyer_count} buyers recently."
        else:
            return f"Balanced activity with {buyer_count} recent buyers and {seller_count} recent sellers."

    def generate_category_narrative(
        self,
        category: str,
        holdings_count: int,
        total_value: float,
        accumulating: int,
        distributing: int,
    ) -> str:
        """Generate narrative for a smart money category."""

        category_names = {
            "Fund": "Institutional Funds",
            "Smart Trader": "All-Time Smart Traders",
            "30D Smart Trader": "30-Day Top Performers",
            "90D Smart Trader": "90-Day Top Performers",
            "180D Smart Trader": "180-Day Top Performers",
            "Smart HL Perps Trader": "Hyperliquid Perps Traders",
        }

        name = category_names.get(category, category)

        # Value formatting
        if total_value >= 1_000_000_000:
            value_str = f"${total_value / 1_000_000_000:.1f}B"
        elif total_value >= 1_000_000:
            value_str = f"${total_value / 1_000_000:.1f}M"
        else:
            value_str = f"${total_value / 1_000:.0f}K"

        # Sentiment
        if accumulating > distributing * 2:
            sentiment = "showing strong conviction"
        elif distributing > accumulating * 2:
            sentiment = "reducing exposure"
        elif accumulating > distributing:
            sentiment = "cautiously accumulating"
        elif distributing > accumulating:
            sentiment = "taking some profits"
        else:
            sentiment = "maintaining positions"

        return f"{name} are {sentiment}. Tracking {holdings_count} token positions worth {value_str}. {accumulating} tokens seeing inflows, {distributing} seeing outflows."
