"""
Whale Tracker

Core logic for tracking whale movements, exchange flows,
and large holder behavior patterns.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import numpy as np

from core.client import SantimentClient
from core.models import ExchangeFlow, WhaleTransaction, HolderLabel


class MovementType(Enum):
    """Types of whale movements."""
    EXCHANGE_DEPOSIT = "exchange_deposit"
    EXCHANGE_WITHDRAWAL = "exchange_withdrawal"
    WHALE_TO_WHALE = "whale_to_whale"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    UNKNOWN = "unknown"


class SignalStrength(Enum):
    """Signal strength classification."""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    EXTREME = "extreme"


@dataclass
class WhaleMovement:
    """Aggregated whale movement data."""
    datetime: datetime
    asset_slug: str
    movement_type: MovementType
    total_value_usd: float
    transaction_count: int
    avg_transaction_size: float
    largest_transaction: float
    signal_strength: SignalStrength
    is_bearish: bool  # Large exchange deposits = bearish

    def to_dict(self) -> dict:
        return {
            "datetime": self.datetime.isoformat(),
            "asset": self.asset_slug,
            "type": self.movement_type.value,
            "total_value_usd": self.total_value_usd,
            "transaction_count": self.transaction_count,
            "avg_size": self.avg_transaction_size,
            "largest": self.largest_transaction,
            "strength": self.signal_strength.value,
            "bearish": self.is_bearish,
        }


@dataclass
class ExchangeFlowAnalysis:
    """Analysis of exchange flow patterns."""
    asset_slug: str
    period_start: datetime
    period_end: datetime

    # Aggregated flows
    total_inflow: float
    total_outflow: float
    net_flow: float

    # Daily statistics
    avg_daily_inflow: float
    avg_daily_outflow: float
    max_daily_inflow: float
    max_daily_outflow: float

    # Trend analysis
    inflow_trend: float  # % change vs previous period
    outflow_trend: float

    # Interpretation
    signal: str  # "bullish", "bearish", "neutral"
    signal_strength: SignalStrength
    interpretation: str

    def to_dict(self) -> dict:
        return {
            "asset": self.asset_slug,
            "period": {
                "start": self.period_start.isoformat(),
                "end": self.period_end.isoformat(),
            },
            "flows": {
                "total_inflow": self.total_inflow,
                "total_outflow": self.total_outflow,
                "net_flow": self.net_flow,
            },
            "daily_stats": {
                "avg_inflow": self.avg_daily_inflow,
                "avg_outflow": self.avg_daily_outflow,
                "max_inflow": self.max_daily_inflow,
                "max_outflow": self.max_daily_outflow,
            },
            "trends": {
                "inflow_change": self.inflow_trend,
                "outflow_change": self.outflow_trend,
            },
            "signal": self.signal,
            "strength": self.signal_strength.value,
            "interpretation": self.interpretation,
        }


@dataclass
class TopHolderSnapshot:
    """Snapshot of top holder positions."""
    asset_slug: str
    snapshot_time: datetime
    holders: list[dict]

    # Aggregated stats
    top_10_balance: float
    top_10_percent: float
    top_100_balance: float
    top_100_percent: float

    # Change tracking
    top_10_change_1d: float
    top_10_change_7d: float
    top_10_change_30d: float

    # Behavior signals
    accumulating: bool
    distributing: bool

    def to_dict(self) -> dict:
        return {
            "asset": self.asset_slug,
            "time": self.snapshot_time.isoformat(),
            "concentration": {
                "top_10_balance": self.top_10_balance,
                "top_10_percent": self.top_10_percent,
                "top_100_balance": self.top_100_balance,
                "top_100_percent": self.top_100_percent,
            },
            "changes": {
                "1d": self.top_10_change_1d,
                "7d": self.top_10_change_7d,
                "30d": self.top_10_change_30d,
            },
            "behavior": {
                "accumulating": self.accumulating,
                "distributing": self.distributing,
            },
            "top_holders": self.holders[:10],  # Only return top 10
        }


class WhaleTracker:
    """
    Tracks whale movements and provides actionable insights.

    Features:
    - Real-time exchange flow monitoring
    - Large transaction detection
    - Top holder tracking
    - Historical pattern analysis
    """

    # Thresholds for signal strength
    THRESHOLDS = {
        "exchange_deposit_weak": 1_000_000,  # $1M
        "exchange_deposit_moderate": 5_000_000,  # $5M
        "exchange_deposit_strong": 20_000_000,  # $20M
        "exchange_deposit_extreme": 100_000_000,  # $100M
    }

    def __init__(self, client: SantimentClient):
        self.client = client

    async def get_exchange_flow_analysis(
        self,
        slug: str,
        days: int = 7,
    ) -> ExchangeFlowAnalysis:
        """
        Analyze exchange flow patterns for an asset.

        Args:
            slug: Asset slug
            days: Number of days to analyze

        Returns:
            ExchangeFlowAnalysis with flows, trends, and interpretation
        """
        now = datetime.utcnow()
        from_date = now - timedelta(days=days)
        prev_from = from_date - timedelta(days=days)

        # Fetch current and previous period flows
        current_flows, prev_flows = await asyncio.gather(
            self.client.get_exchange_flow(slug, from_date, now),
            self.client.get_exchange_flow(slug, prev_from, from_date),
            return_exceptions=True,
        )

        if isinstance(current_flows, Exception) or not current_flows:
            current_flows = []
        if isinstance(prev_flows, Exception):
            prev_flows = []

        # Calculate aggregates
        total_inflow = sum(f.inflow for f in current_flows)
        total_outflow = sum(f.outflow for f in current_flows)
        net_flow = total_inflow - total_outflow

        inflows = [f.inflow for f in current_flows]
        outflows = [f.outflow for f in current_flows]

        avg_daily_inflow = np.mean(inflows) if inflows else 0
        avg_daily_outflow = np.mean(outflows) if outflows else 0
        max_daily_inflow = max(inflows) if inflows else 0
        max_daily_outflow = max(outflows) if outflows else 0

        # Calculate trends
        prev_total_inflow = sum(f.inflow for f in prev_flows) if prev_flows else total_inflow
        prev_total_outflow = sum(f.outflow for f in prev_flows) if prev_flows else total_outflow

        inflow_trend = ((total_inflow - prev_total_inflow) / prev_total_inflow * 100) if prev_total_inflow > 0 else 0
        outflow_trend = ((total_outflow - prev_total_outflow) / prev_total_outflow * 100) if prev_total_outflow > 0 else 0

        # Determine signal
        signal, strength, interpretation = self._interpret_exchange_flow(
            net_flow, total_inflow, total_outflow, inflow_trend, outflow_trend
        )

        return ExchangeFlowAnalysis(
            asset_slug=slug,
            period_start=from_date,
            period_end=now,
            total_inflow=total_inflow,
            total_outflow=total_outflow,
            net_flow=net_flow,
            avg_daily_inflow=avg_daily_inflow,
            avg_daily_outflow=avg_daily_outflow,
            max_daily_inflow=max_daily_inflow,
            max_daily_outflow=max_daily_outflow,
            inflow_trend=inflow_trend,
            outflow_trend=outflow_trend,
            signal=signal,
            signal_strength=strength,
            interpretation=interpretation,
        )

    def _interpret_exchange_flow(
        self,
        net_flow: float,
        total_inflow: float,
        total_outflow: float,
        inflow_trend: float,
        outflow_trend: float,
    ) -> tuple[str, SignalStrength, str]:
        """Interpret exchange flow data into actionable signal."""

        # Determine direction
        if abs(net_flow) < total_inflow * 0.1:  # Less than 10% net change
            signal = "neutral"
            interpretation = "Balanced exchange flows - no clear directional signal"
        elif net_flow > 0:
            signal = "bearish"
            interpretation = "Net inflow to exchanges - potential selling pressure"
        else:
            signal = "bullish"
            interpretation = "Net outflow from exchanges - accumulation signal"

        # Determine strength
        net_ratio = abs(net_flow) / max(total_inflow, 1)

        if net_ratio < 0.15:
            strength = SignalStrength.WEAK
        elif net_ratio < 0.30:
            strength = SignalStrength.MODERATE
        elif net_ratio < 0.50:
            strength = SignalStrength.STRONG
        else:
            strength = SignalStrength.EXTREME

        # Enhance interpretation with trend data
        if signal == "bearish" and inflow_trend > 50:
            interpretation += f" - Inflows accelerating ({inflow_trend:.0f}% vs prev period)"
            if strength.value in ["weak", "moderate"]:
                strength = SignalStrength(["weak", "moderate", "strong", "extreme"][
                    min(3, ["weak", "moderate", "strong", "extreme"].index(strength.value) + 1)
                ])
        elif signal == "bullish" and outflow_trend > 50:
            interpretation += f" - Withdrawals accelerating ({outflow_trend:.0f}% vs prev period)"

        return signal, strength, interpretation

    async def get_top_holder_snapshot(
        self,
        slug: str,
    ) -> TopHolderSnapshot:
        """Get current top holder positions and changes."""
        holders = await self.client.get_top_holders(slug, 100)

        if not holders:
            return TopHolderSnapshot(
                asset_slug=slug,
                snapshot_time=datetime.utcnow(),
                holders=[],
                top_10_balance=0,
                top_10_percent=0,
                top_100_balance=0,
                top_100_percent=0,
                top_10_change_1d=0,
                top_10_change_7d=0,
                top_10_change_30d=0,
                accumulating=False,
                distributing=False,
            )

        top_10 = holders[:10]
        top_10_balance = sum(h.get("balance", 0) for h in top_10)
        top_100_balance = sum(h.get("balance", 0) for h in holders)

        # Calculate percentage changes
        top_10_change_1d = sum(h.get("balanceChange1d", 0) for h in top_10)
        top_10_change_7d = sum(h.get("balanceChange7d", 0) for h in top_10)
        top_10_change_30d = sum(h.get("balanceChange30d", 0) for h in top_10)

        # Determine behavior
        accumulating = top_10_change_7d > 0 and top_10_change_30d > 0
        distributing = top_10_change_7d < 0 and top_10_change_30d < 0

        return TopHolderSnapshot(
            asset_slug=slug,
            snapshot_time=datetime.utcnow(),
            holders=holders,
            top_10_balance=top_10_balance,
            top_10_percent=0,  # Would need total supply
            top_100_balance=top_100_balance,
            top_100_percent=0,
            top_10_change_1d=top_10_change_1d,
            top_10_change_7d=top_10_change_7d,
            top_10_change_30d=top_10_change_30d,
            accumulating=accumulating,
            distributing=distributing,
        )

    async def get_whale_movements(
        self,
        slug: str,
        hours: int = 24,
        min_value_usd: float = 1_000_000,
    ) -> list[WhaleMovement]:
        """
        Get recent whale movements for an asset.

        Args:
            slug: Asset slug
            hours: Lookback period in hours
            min_value_usd: Minimum transaction value to consider

        Returns:
            List of whale movements
        """
        now = datetime.utcnow()
        from_date = now - timedelta(hours=hours)

        transactions = await self.client.get_whale_transactions(
            slug, from_date, now, min_value_usd
        )

        # Group transactions by type
        deposits = [t for t in transactions if t.is_exchange_deposit]
        withdrawals = [t for t in transactions if t.is_exchange_withdrawal]
        other = [t for t in transactions if not t.is_exchange_flow]

        movements = []

        # Aggregate deposits
        if deposits:
            total_deposit = sum(t.value_usd for t in deposits)
            movements.append(
                WhaleMovement(
                    datetime=now,
                    asset_slug=slug,
                    movement_type=MovementType.EXCHANGE_DEPOSIT,
                    total_value_usd=total_deposit,
                    transaction_count=len(deposits),
                    avg_transaction_size=total_deposit / len(deposits),
                    largest_transaction=max(t.value_usd for t in deposits),
                    signal_strength=self._get_signal_strength(total_deposit),
                    is_bearish=True,
                )
            )

        # Aggregate withdrawals
        if withdrawals:
            total_withdrawal = sum(t.value_usd for t in withdrawals)
            movements.append(
                WhaleMovement(
                    datetime=now,
                    asset_slug=slug,
                    movement_type=MovementType.EXCHANGE_WITHDRAWAL,
                    total_value_usd=total_withdrawal,
                    transaction_count=len(withdrawals),
                    avg_transaction_size=total_withdrawal / len(withdrawals),
                    largest_transaction=max(t.value_usd for t in withdrawals),
                    signal_strength=self._get_signal_strength(total_withdrawal),
                    is_bearish=False,
                )
            )

        # Aggregate other large movements
        if other:
            total_other = sum(t.value_usd for t in other)
            movements.append(
                WhaleMovement(
                    datetime=now,
                    asset_slug=slug,
                    movement_type=MovementType.WHALE_TO_WHALE,
                    total_value_usd=total_other,
                    transaction_count=len(other),
                    avg_transaction_size=total_other / len(other),
                    largest_transaction=max(t.value_usd for t in other),
                    signal_strength=self._get_signal_strength(total_other),
                    is_bearish=False,  # Neutral
                )
            )

        return movements

    def _get_signal_strength(self, value_usd: float) -> SignalStrength:
        """Determine signal strength based on USD value."""
        if value_usd >= self.THRESHOLDS["exchange_deposit_extreme"]:
            return SignalStrength.EXTREME
        elif value_usd >= self.THRESHOLDS["exchange_deposit_strong"]:
            return SignalStrength.STRONG
        elif value_usd >= self.THRESHOLDS["exchange_deposit_moderate"]:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK

    async def get_whale_dashboard(
        self,
        slug: str,
    ) -> dict:
        """
        Get comprehensive whale dashboard data for an asset.

        Returns combined view of:
        - Exchange flows
        - Top holder positions
        - Recent movements
        - Overall whale sentiment
        """
        # Fetch all data in parallel
        flow_analysis, top_holders, movements_24h, movements_7d = await asyncio.gather(
            self.get_exchange_flow_analysis(slug, days=7),
            self.get_top_holder_snapshot(slug),
            self.get_whale_movements(slug, hours=24),
            self.get_whale_movements(slug, hours=168),  # 7 days
            return_exceptions=True,
        )

        # Handle errors gracefully
        if isinstance(flow_analysis, Exception):
            flow_analysis = None
        if isinstance(top_holders, Exception):
            top_holders = None
        if isinstance(movements_24h, Exception):
            movements_24h = []
        if isinstance(movements_7d, Exception):
            movements_7d = []

        # Calculate overall whale sentiment
        bullish_signals = 0
        bearish_signals = 0

        if flow_analysis and flow_analysis.signal == "bullish":
            bullish_signals += 2 if flow_analysis.signal_strength in [SignalStrength.STRONG, SignalStrength.EXTREME] else 1
        elif flow_analysis and flow_analysis.signal == "bearish":
            bearish_signals += 2 if flow_analysis.signal_strength in [SignalStrength.STRONG, SignalStrength.EXTREME] else 1

        if top_holders and top_holders.accumulating:
            bullish_signals += 1
        elif top_holders and top_holders.distributing:
            bearish_signals += 1

        deposit_volume = sum(m.total_value_usd for m in movements_24h if m.movement_type == MovementType.EXCHANGE_DEPOSIT)
        withdrawal_volume = sum(m.total_value_usd for m in movements_24h if m.movement_type == MovementType.EXCHANGE_WITHDRAWAL)

        if withdrawal_volume > deposit_volume * 1.5:
            bullish_signals += 1
        elif deposit_volume > withdrawal_volume * 1.5:
            bearish_signals += 1

        # Overall sentiment
        if bullish_signals > bearish_signals + 1:
            overall_sentiment = "bullish"
        elif bearish_signals > bullish_signals + 1:
            overall_sentiment = "bearish"
        else:
            overall_sentiment = "neutral"

        return {
            "asset": slug,
            "timestamp": datetime.utcnow().isoformat(),
            "overall_sentiment": overall_sentiment,
            "sentiment_breakdown": {
                "bullish_signals": bullish_signals,
                "bearish_signals": bearish_signals,
            },
            "exchange_flows": flow_analysis.to_dict() if flow_analysis else None,
            "top_holders": top_holders.to_dict() if top_holders else None,
            "movements_24h": [m.to_dict() for m in movements_24h],
            "movements_7d_summary": {
                "total_deposit_volume": sum(m.total_value_usd for m in movements_7d if m.movement_type == MovementType.EXCHANGE_DEPOSIT),
                "total_withdrawal_volume": sum(m.total_value_usd for m in movements_7d if m.movement_type == MovementType.EXCHANGE_WITHDRAWAL),
                "total_transactions": sum(m.transaction_count for m in movements_7d),
            },
        }
