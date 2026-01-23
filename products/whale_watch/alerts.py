"""
Whale Alert Engine

Real-time alerting system for whale movements with
configurable thresholds and notification channels.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional

from core.client import SantimentClient
from core.models import Alert
from .tracker import WhaleTracker, MovementType, SignalStrength


class AlertType(Enum):
    """Types of whale alerts."""
    LARGE_EXCHANGE_DEPOSIT = "large_exchange_deposit"
    LARGE_EXCHANGE_WITHDRAWAL = "large_exchange_withdrawal"
    WHALE_ACCUMULATION = "whale_accumulation"
    WHALE_DISTRIBUTION = "whale_distribution"
    EXCHANGE_FLOW_SPIKE = "exchange_flow_spike"
    TOP_HOLDER_MOVEMENT = "top_holder_movement"


class AlertSeverity(Enum):
    """Alert severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AlertConfig:
    """Configuration for whale alerts."""
    # Asset to monitor
    asset_slug: str

    # Thresholds (in USD)
    deposit_threshold: float = 5_000_000
    withdrawal_threshold: float = 5_000_000

    # Percentage thresholds
    flow_spike_percent: float = 100  # Alert if flow is 100% above average
    top_holder_change_percent: float = 5  # Alert if top 10 change > 5%

    # Alert types to enable
    enabled_alerts: list[AlertType] = field(default_factory=lambda: list(AlertType))

    # Cooldown between alerts of same type (minutes)
    cooldown_minutes: int = 30


@dataclass
class WhaleAlert:
    """A whale alert instance."""
    id: str
    created_at: datetime
    alert_type: AlertType
    severity: AlertSeverity
    asset_slug: str
    title: str
    message: str
    value_usd: Optional[float] = None
    transaction_count: Optional[int] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "type": self.alert_type.value,
            "severity": self.severity.value,
            "asset": self.asset_slug,
            "title": self.title,
            "message": self.message,
            "value_usd": self.value_usd,
            "transaction_count": self.transaction_count,
            "metadata": self.metadata,
        }

    def to_core_alert(self) -> Alert:
        """Convert to core Alert model."""
        return Alert(
            id=self.id,
            created_at=self.created_at,
            alert_type=self.alert_type.value,
            asset_slug=self.asset_slug,
            title=self.title,
            message=self.message,
            severity=self.severity.value,
            data={
                "value_usd": self.value_usd,
                "transaction_count": self.transaction_count,
                **self.metadata,
            },
        )


# Type for alert handlers
AlertHandler = Callable[[WhaleAlert], None]


class WhaleAlertEngine:
    """
    Real-time whale alert monitoring engine.

    Features:
    - Configurable alert thresholds
    - Multiple notification channels
    - Alert deduplication and cooldown
    - Historical alert tracking
    """

    def __init__(self, client: SantimentClient):
        self.client = client
        self.tracker = WhaleTracker(client)
        self._configs: dict[str, AlertConfig] = {}
        self._handlers: list[AlertHandler] = []
        self._alert_history: list[WhaleAlert] = []
        self._last_alert_times: dict[str, datetime] = {}
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

    def add_config(self, config: AlertConfig) -> None:
        """Add or update alert configuration for an asset."""
        self._configs[config.asset_slug] = config

    def remove_config(self, asset_slug: str) -> None:
        """Remove alert configuration for an asset."""
        self._configs.pop(asset_slug, None)

    def add_handler(self, handler: AlertHandler) -> None:
        """Add an alert handler (callback for new alerts)."""
        self._handlers.append(handler)

    def remove_handler(self, handler: AlertHandler) -> None:
        """Remove an alert handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    async def check_alerts(self, asset_slug: str) -> list[WhaleAlert]:
        """
        Check for alerts on a specific asset.

        Returns list of triggered alerts.
        """
        config = self._configs.get(asset_slug)
        if not config:
            return []

        alerts = []

        # Get current whale data
        dashboard = await self.tracker.get_whale_dashboard(asset_slug)

        # Check exchange deposit alerts
        if AlertType.LARGE_EXCHANGE_DEPOSIT in config.enabled_alerts:
            alert = self._check_deposit_alert(dashboard, config)
            if alert and self._should_fire(alert):
                alerts.append(alert)

        # Check exchange withdrawal alerts
        if AlertType.LARGE_EXCHANGE_WITHDRAWAL in config.enabled_alerts:
            alert = self._check_withdrawal_alert(dashboard, config)
            if alert and self._should_fire(alert):
                alerts.append(alert)

        # Check exchange flow spike
        if AlertType.EXCHANGE_FLOW_SPIKE in config.enabled_alerts:
            alert = self._check_flow_spike_alert(dashboard, config)
            if alert and self._should_fire(alert):
                alerts.append(alert)

        # Check top holder movement
        if AlertType.TOP_HOLDER_MOVEMENT in config.enabled_alerts:
            alert = self._check_top_holder_alert(dashboard, config)
            if alert and self._should_fire(alert):
                alerts.append(alert)

        # Check accumulation/distribution
        if AlertType.WHALE_ACCUMULATION in config.enabled_alerts:
            alert = self._check_accumulation_alert(dashboard, config)
            if alert and self._should_fire(alert):
                alerts.append(alert)

        if AlertType.WHALE_DISTRIBUTION in config.enabled_alerts:
            alert = self._check_distribution_alert(dashboard, config)
            if alert and self._should_fire(alert):
                alerts.append(alert)

        # Fire handlers and record alerts
        for alert in alerts:
            self._record_alert(alert)
            for handler in self._handlers:
                try:
                    handler(alert)
                except Exception:
                    pass  # Don't let handler errors stop other handlers

        return alerts

    def _check_deposit_alert(
        self,
        dashboard: dict,
        config: AlertConfig,
    ) -> Optional[WhaleAlert]:
        """Check for large exchange deposit alert."""
        movements = dashboard.get("movements_24h", [])
        deposits = [m for m in movements if m.get("type") == MovementType.EXCHANGE_DEPOSIT.value]

        if not deposits:
            return None

        total_deposit = sum(d.get("total_value_usd", 0) for d in deposits)

        if total_deposit < config.deposit_threshold:
            return None

        severity = self._get_severity(total_deposit, config.deposit_threshold)

        return WhaleAlert(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            alert_type=AlertType.LARGE_EXCHANGE_DEPOSIT,
            severity=severity,
            asset_slug=config.asset_slug,
            title=f"Large Exchange Deposit: {config.asset_slug.upper()}",
            message=f"${total_deposit:,.0f} deposited to exchanges in the last 24h. "
                    f"This may indicate upcoming selling pressure.",
            value_usd=total_deposit,
            transaction_count=sum(d.get("transaction_count", 0) for d in deposits),
            metadata={"movements": deposits},
        )

    def _check_withdrawal_alert(
        self,
        dashboard: dict,
        config: AlertConfig,
    ) -> Optional[WhaleAlert]:
        """Check for large exchange withdrawal alert."""
        movements = dashboard.get("movements_24h", [])
        withdrawals = [m for m in movements if m.get("type") == MovementType.EXCHANGE_WITHDRAWAL.value]

        if not withdrawals:
            return None

        total_withdrawal = sum(w.get("total_value_usd", 0) for w in withdrawals)

        if total_withdrawal < config.withdrawal_threshold:
            return None

        severity = self._get_severity(total_withdrawal, config.withdrawal_threshold)

        return WhaleAlert(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            alert_type=AlertType.LARGE_EXCHANGE_WITHDRAWAL,
            severity=severity,
            asset_slug=config.asset_slug,
            title=f"Large Exchange Withdrawal: {config.asset_slug.upper()}",
            message=f"${total_withdrawal:,.0f} withdrawn from exchanges in the last 24h. "
                    f"Whales may be accumulating for long-term holding.",
            value_usd=total_withdrawal,
            transaction_count=sum(w.get("transaction_count", 0) for w in withdrawals),
            metadata={"movements": withdrawals},
        )

    def _check_flow_spike_alert(
        self,
        dashboard: dict,
        config: AlertConfig,
    ) -> Optional[WhaleAlert]:
        """Check for exchange flow spike alert."""
        flows = dashboard.get("exchange_flows")
        if not flows:
            return None

        inflow_trend = flows.get("trends", {}).get("inflow_change", 0)
        outflow_trend = flows.get("trends", {}).get("outflow_change", 0)

        max_change = max(abs(inflow_trend), abs(outflow_trend))

        if max_change < config.flow_spike_percent:
            return None

        is_inflow_spike = abs(inflow_trend) > abs(outflow_trend)
        direction = "inflow" if is_inflow_spike else "outflow"
        change = inflow_trend if is_inflow_spike else outflow_trend

        severity = AlertSeverity.MEDIUM if max_change < 200 else AlertSeverity.HIGH

        return WhaleAlert(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            alert_type=AlertType.EXCHANGE_FLOW_SPIKE,
            severity=severity,
            asset_slug=config.asset_slug,
            title=f"Exchange Flow Spike: {config.asset_slug.upper()}",
            message=f"Exchange {direction} has spiked {change:.0f}% vs previous period. "
                    f"{'Bearish signal - potential selling incoming.' if is_inflow_spike else 'Bullish signal - accumulation detected.'}",
            metadata={
                "direction": direction,
                "change_percent": change,
                "flows": flows,
            },
        )

    def _check_top_holder_alert(
        self,
        dashboard: dict,
        config: AlertConfig,
    ) -> Optional[WhaleAlert]:
        """Check for significant top holder movement."""
        holders = dashboard.get("top_holders")
        if not holders:
            return None

        changes = holders.get("changes", {})
        change_7d = changes.get("7d", 0)

        # Calculate as percentage of top 10 balance
        top_10_balance = holders.get("concentration", {}).get("top_10_balance", 0)
        if top_10_balance == 0:
            return None

        change_percent = abs(change_7d / top_10_balance * 100)

        if change_percent < config.top_holder_change_percent:
            return None

        is_accumulating = change_7d > 0
        action = "accumulated" if is_accumulating else "distributed"

        return WhaleAlert(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            alert_type=AlertType.TOP_HOLDER_MOVEMENT,
            severity=AlertSeverity.MEDIUM,
            asset_slug=config.asset_slug,
            title=f"Top Holder Movement: {config.asset_slug.upper()}",
            message=f"Top 10 holders have {action} {change_percent:.1f}% of their position in the past 7 days. "
                    f"{'Whales are buying.' if is_accumulating else 'Whales may be selling.'}",
            metadata={
                "change_7d": change_7d,
                "change_percent": change_percent,
                "direction": "accumulating" if is_accumulating else "distributing",
            },
        )

    def _check_accumulation_alert(
        self,
        dashboard: dict,
        config: AlertConfig,
    ) -> Optional[WhaleAlert]:
        """Check for whale accumulation pattern."""
        holders = dashboard.get("top_holders")
        flows = dashboard.get("exchange_flows")

        if not holders or not flows:
            return None

        is_accumulating = holders.get("behavior", {}).get("accumulating", False)
        is_outflow = flows.get("signal") == "bullish"

        if not (is_accumulating and is_outflow):
            return None

        return WhaleAlert(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            alert_type=AlertType.WHALE_ACCUMULATION,
            severity=AlertSeverity.HIGH,
            asset_slug=config.asset_slug,
            title=f"Whale Accumulation Detected: {config.asset_slug.upper()}",
            message="Multiple signals indicate whale accumulation: "
                    "Top holders increasing positions AND net outflow from exchanges. "
                    "This is historically a bullish pattern.",
            metadata={
                "top_holder_behavior": holders.get("behavior"),
                "exchange_signal": flows.get("signal"),
            },
        )

    def _check_distribution_alert(
        self,
        dashboard: dict,
        config: AlertConfig,
    ) -> Optional[WhaleAlert]:
        """Check for whale distribution pattern."""
        holders = dashboard.get("top_holders")
        flows = dashboard.get("exchange_flows")

        if not holders or not flows:
            return None

        is_distributing = holders.get("behavior", {}).get("distributing", False)
        is_inflow = flows.get("signal") == "bearish"

        if not (is_distributing and is_inflow):
            return None

        return WhaleAlert(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            alert_type=AlertType.WHALE_DISTRIBUTION,
            severity=AlertSeverity.CRITICAL,
            asset_slug=config.asset_slug,
            title=f"Whale Distribution Detected: {config.asset_slug.upper()}",
            message="WARNING: Multiple signals indicate whale distribution: "
                    "Top holders reducing positions AND net inflow to exchanges. "
                    "This is historically a bearish pattern - potential selling incoming.",
            metadata={
                "top_holder_behavior": holders.get("behavior"),
                "exchange_signal": flows.get("signal"),
            },
        )

    def _get_severity(self, value: float, threshold: float) -> AlertSeverity:
        """Determine alert severity based on value vs threshold."""
        ratio = value / threshold
        if ratio >= 10:
            return AlertSeverity.CRITICAL
        elif ratio >= 5:
            return AlertSeverity.HIGH
        elif ratio >= 2:
            return AlertSeverity.MEDIUM
        else:
            return AlertSeverity.LOW

    def _should_fire(self, alert: WhaleAlert) -> bool:
        """Check if alert should fire based on cooldown."""
        key = f"{alert.asset_slug}:{alert.alert_type.value}"
        last_time = self._last_alert_times.get(key)

        if last_time is None:
            return True

        config = self._configs.get(alert.asset_slug)
        cooldown = timedelta(minutes=config.cooldown_minutes if config else 30)

        return datetime.utcnow() - last_time > cooldown

    def _record_alert(self, alert: WhaleAlert) -> None:
        """Record alert in history and update last fire time."""
        key = f"{alert.asset_slug}:{alert.alert_type.value}"
        self._last_alert_times[key] = alert.created_at
        self._alert_history.append(alert)

        # Keep history limited
        if len(self._alert_history) > 1000:
            self._alert_history = self._alert_history[-500:]

    async def start_monitoring(self, interval_seconds: int = 300) -> None:
        """Start background monitoring of all configured assets."""
        if self._running:
            return

        self._running = True

        async def monitor_loop():
            while self._running:
                for slug in list(self._configs.keys()):
                    try:
                        await self.check_alerts(slug)
                    except Exception:
                        pass  # Log error but continue
                await asyncio.sleep(interval_seconds)

        self._monitor_task = asyncio.create_task(monitor_loop())

    async def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    def get_alert_history(
        self,
        asset_slug: Optional[str] = None,
        alert_type: Optional[AlertType] = None,
        limit: int = 50,
    ) -> list[WhaleAlert]:
        """Get historical alerts with optional filtering."""
        alerts = self._alert_history

        if asset_slug:
            alerts = [a for a in alerts if a.asset_slug == asset_slug]

        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]

        return alerts[-limit:]
