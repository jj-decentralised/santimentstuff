"""
Whale Watch REST API

FastAPI-based REST API for whale tracking and alerts.
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.client import SantimentClient
from core.cache import CacheManager
from .tracker import WhaleTracker
from .alerts import WhaleAlertEngine, AlertConfig, AlertType, WhaleAlert


# ==================== Pydantic Models ====================

class ExchangeFlowResponse(BaseModel):
    """Response model for exchange flow analysis."""
    asset: str
    period_start: datetime
    period_end: datetime
    total_inflow: float
    total_outflow: float
    net_flow: float
    signal: str
    signal_strength: str
    interpretation: str


class TopHolderResponse(BaseModel):
    """Response model for top holder data."""
    asset: str
    snapshot_time: datetime
    top_10_balance: float
    top_10_change_1d: float
    top_10_change_7d: float
    top_10_change_30d: float
    accumulating: bool
    distributing: bool
    top_holders: list[dict]


class WhaleMovementResponse(BaseModel):
    """Response model for whale movements."""
    datetime: datetime
    asset: str
    movement_type: str
    total_value_usd: float
    transaction_count: int
    signal_strength: str
    is_bearish: bool


class DashboardResponse(BaseModel):
    """Response model for whale dashboard."""
    asset: str
    timestamp: datetime
    overall_sentiment: str
    sentiment_breakdown: dict
    exchange_flows: Optional[dict]
    top_holders: Optional[dict]
    movements_24h: list[dict]
    movements_7d_summary: dict


class AlertConfigRequest(BaseModel):
    """Request model for alert configuration."""
    asset_slug: str
    deposit_threshold: float = Field(default=5_000_000, ge=100_000)
    withdrawal_threshold: float = Field(default=5_000_000, ge=100_000)
    flow_spike_percent: float = Field(default=100, ge=10)
    top_holder_change_percent: float = Field(default=5, ge=1)
    enabled_alerts: list[str] = Field(default_factory=lambda: [t.value for t in AlertType])
    cooldown_minutes: int = Field(default=30, ge=5)


class AlertResponse(BaseModel):
    """Response model for whale alerts."""
    id: str
    created_at: datetime
    alert_type: str
    severity: str
    asset: str
    title: str
    message: str
    value_usd: Optional[float]
    transaction_count: Optional[int]


# ==================== Dependencies ====================

_client: Optional[SantimentClient] = None
_tracker: Optional[WhaleTracker] = None
_alert_engine: Optional[WhaleAlertEngine] = None


async def get_tracker() -> WhaleTracker:
    """Dependency to get the whale tracker."""
    global _client, _tracker
    if _tracker is None:
        cache = CacheManager.create(use_redis=False)
        _client = SantimentClient(cache=cache)
        await _client.__aenter__()
        _tracker = WhaleTracker(_client)
    return _tracker


async def get_alert_engine() -> WhaleAlertEngine:
    """Dependency to get the alert engine."""
    global _client, _alert_engine
    if _alert_engine is None:
        if _client is None:
            cache = CacheManager.create(use_redis=False)
            _client = SantimentClient(cache=cache)
            await _client.__aenter__()
        _alert_engine = WhaleAlertEngine(_client)
    return _alert_engine


# ==================== WebSocket Manager ====================

class ConnectionManager:
    """Manage WebSocket connections for real-time alerts."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, asset_slug: str):
        await websocket.accept()
        if asset_slug not in self.active_connections:
            self.active_connections[asset_slug] = []
        self.active_connections[asset_slug].append(websocket)

    def disconnect(self, websocket: WebSocket, asset_slug: str):
        if asset_slug in self.active_connections:
            if websocket in self.active_connections[asset_slug]:
                self.active_connections[asset_slug].remove(websocket)

    async def broadcast(self, asset_slug: str, message: dict):
        if asset_slug in self.active_connections:
            for connection in self.active_connections[asset_slug]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass


manager = ConnectionManager()


# ==================== App Factory ====================

def create_whale_watch_app() -> FastAPI:
    """Create the FastAPI application for Whale Watch."""

    app = FastAPI(
        title="Whale Watch API",
        description="""
        Real-time whale tracking and alert system for cryptocurrency assets.

        ## Features
        - **Exchange Flow Analysis**: Track deposits/withdrawals to exchanges
        - **Top Holder Tracking**: Monitor whale wallet positions
        - **Movement Detection**: Detect large transactions in real-time
        - **Smart Alerts**: Configurable alerts for whale activity
        - **WebSocket Support**: Real-time alert streaming

        ## Signal Interpretation
        - **Bearish**: Large exchange deposits often precede selling
        - **Bullish**: Large withdrawals suggest long-term accumulation
        - **Accumulation**: Top holders increasing + net outflows
        - **Distribution**: Top holders decreasing + net inflows
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ==================== Dashboard Endpoints ====================

    @app.get("/")
    async def root():
        """API root with service information."""
        return {
            "service": "Whale Watch API",
            "version": "1.0.0",
            "endpoints": {
                "dashboard": "/dashboard/{slug}",
                "exchange_flows": "/flows/{slug}",
                "top_holders": "/holders/{slug}",
                "movements": "/movements/{slug}",
                "alerts": "/alerts",
                "websocket": "/ws/{slug}",
            }
        }

    @app.get("/dashboard/{slug}", response_model=DashboardResponse)
    async def get_whale_dashboard(
        slug: str,
        tracker: WhaleTracker = Depends(get_tracker),
    ):
        """
        Get comprehensive whale dashboard for an asset.

        Combines exchange flows, top holders, and recent movements
        into a single view with overall sentiment analysis.
        """
        try:
            dashboard = await tracker.get_whale_dashboard(slug)
            return DashboardResponse(
                asset=dashboard["asset"],
                timestamp=datetime.fromisoformat(dashboard["timestamp"]),
                overall_sentiment=dashboard["overall_sentiment"],
                sentiment_breakdown=dashboard["sentiment_breakdown"],
                exchange_flows=dashboard["exchange_flows"],
                top_holders=dashboard["top_holders"],
                movements_24h=dashboard["movements_24h"],
                movements_7d_summary=dashboard["movements_7d_summary"],
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/flows/{slug}")
    async def get_exchange_flows(
        slug: str,
        days: int = Query(default=7, ge=1, le=90),
        tracker: WhaleTracker = Depends(get_tracker),
    ):
        """
        Get detailed exchange flow analysis.

        - **days**: Analysis period (default: 7)
        """
        try:
            analysis = await tracker.get_exchange_flow_analysis(slug, days)
            return analysis.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/holders/{slug}")
    async def get_top_holders(
        slug: str,
        tracker: WhaleTracker = Depends(get_tracker),
    ):
        """
        Get top holder positions and changes.

        Returns top 100 holders with balance changes over 1d, 7d, 30d.
        """
        try:
            snapshot = await tracker.get_top_holder_snapshot(slug)
            return snapshot.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/movements/{slug}", response_model=list[WhaleMovementResponse])
    async def get_whale_movements(
        slug: str,
        hours: int = Query(default=24, ge=1, le=168),
        min_value_usd: float = Query(default=1_000_000, ge=100_000),
        tracker: WhaleTracker = Depends(get_tracker),
    ):
        """
        Get recent whale movements.

        - **hours**: Lookback period (default: 24)
        - **min_value_usd**: Minimum transaction value (default: $1M)
        """
        try:
            movements = await tracker.get_whale_movements(slug, hours, min_value_usd)
            return [
                WhaleMovementResponse(
                    datetime=m.datetime,
                    asset=m.asset_slug,
                    movement_type=m.movement_type.value,
                    total_value_usd=m.total_value_usd,
                    transaction_count=m.transaction_count,
                    signal_strength=m.signal_strength.value,
                    is_bearish=m.is_bearish,
                )
                for m in movements
            ]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== Alert Endpoints ====================

    @app.post("/alerts/config")
    async def configure_alerts(
        config: AlertConfigRequest,
        engine: WhaleAlertEngine = Depends(get_alert_engine),
    ):
        """
        Configure alerts for an asset.

        Set thresholds and enable/disable alert types.
        """
        try:
            alert_config = AlertConfig(
                asset_slug=config.asset_slug,
                deposit_threshold=config.deposit_threshold,
                withdrawal_threshold=config.withdrawal_threshold,
                flow_spike_percent=config.flow_spike_percent,
                top_holder_change_percent=config.top_holder_change_percent,
                enabled_alerts=[AlertType(t) for t in config.enabled_alerts],
                cooldown_minutes=config.cooldown_minutes,
            )
            engine.add_config(alert_config)

            return {
                "status": "configured",
                "asset": config.asset_slug,
                "config": config.model_dump(),
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/alerts/config/{slug}")
    async def remove_alert_config(
        slug: str,
        engine: WhaleAlertEngine = Depends(get_alert_engine),
    ):
        """Remove alert configuration for an asset."""
        engine.remove_config(slug)
        return {"status": "removed", "asset": slug}

    @app.get("/alerts/check/{slug}", response_model=list[AlertResponse])
    async def check_alerts_now(
        slug: str,
        engine: WhaleAlertEngine = Depends(get_alert_engine),
    ):
        """
        Manually trigger alert check for an asset.

        Returns any alerts that would be triggered based on current data.
        """
        try:
            # Ensure config exists (use defaults if not)
            if slug not in engine._configs:
                engine.add_config(AlertConfig(asset_slug=slug))

            alerts = await engine.check_alerts(slug)
            return [
                AlertResponse(
                    id=a.id,
                    created_at=a.created_at,
                    alert_type=a.alert_type.value,
                    severity=a.severity.value,
                    asset=a.asset_slug,
                    title=a.title,
                    message=a.message,
                    value_usd=a.value_usd,
                    transaction_count=a.transaction_count,
                )
                for a in alerts
            ]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/alerts/history", response_model=list[AlertResponse])
    async def get_alert_history(
        asset_slug: Optional[str] = None,
        alert_type: Optional[str] = None,
        limit: int = Query(default=50, ge=1, le=200),
        engine: WhaleAlertEngine = Depends(get_alert_engine),
    ):
        """
        Get historical alerts.

        - **asset_slug**: Filter by asset (optional)
        - **alert_type**: Filter by alert type (optional)
        - **limit**: Maximum alerts to return (default: 50)
        """
        try:
            type_filter = AlertType(alert_type) if alert_type else None
            alerts = engine.get_alert_history(asset_slug, type_filter, limit)
            return [
                AlertResponse(
                    id=a.id,
                    created_at=a.created_at,
                    alert_type=a.alert_type.value,
                    severity=a.severity.value,
                    asset=a.asset_slug,
                    title=a.title,
                    message=a.message,
                    value_usd=a.value_usd,
                    transaction_count=a.transaction_count,
                )
                for a in alerts
            ]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== WebSocket Endpoint ====================

    @app.websocket("/ws/{slug}")
    async def websocket_endpoint(
        websocket: WebSocket,
        slug: str,
    ):
        """
        WebSocket endpoint for real-time alerts.

        Connect to receive alerts for a specific asset in real-time.
        """
        await manager.connect(websocket, slug)

        # Set up alert handler to broadcast to WebSocket
        engine = await get_alert_engine()

        def broadcast_alert(alert: WhaleAlert):
            import asyncio
            asyncio.create_task(manager.broadcast(slug, alert.to_dict()))

        engine.add_handler(broadcast_alert)

        # Ensure config exists
        if slug not in engine._configs:
            engine.add_config(AlertConfig(asset_slug=slug))

        try:
            while True:
                # Keep connection alive and listen for client messages
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                elif data == "check":
                    # Manual check triggered by client
                    alerts = await engine.check_alerts(slug)
                    for alert in alerts:
                        await websocket.send_json(alert.to_dict())
        except WebSocketDisconnect:
            manager.disconnect(websocket, slug)
            engine.remove_handler(broadcast_alert)

    # ==================== Multi-Asset Endpoints ====================

    @app.post("/dashboard/batch")
    async def get_batch_dashboards(
        slugs: list[str],
        tracker: WhaleTracker = Depends(get_tracker),
    ):
        """
        Get dashboards for multiple assets.

        Maximum 10 assets per request.
        """
        if len(slugs) > 10:
            raise HTTPException(status_code=400, detail="Maximum 10 assets per request")

        import asyncio
        results = await asyncio.gather(
            *[tracker.get_whale_dashboard(slug) for slug in slugs],
            return_exceptions=True,
        )

        dashboards = []
        for slug, result in zip(slugs, results):
            if isinstance(result, Exception):
                dashboards.append({"asset": slug, "error": str(result)})
            else:
                dashboards.append(result)

        return {"dashboards": dashboards, "count": len(dashboards)}

    @app.get("/leaderboard/bearish")
    async def get_bearish_leaderboard(
        tracker: WhaleTracker = Depends(get_tracker),
    ):
        """
        Get assets with the most bearish whale signals.

        Shows top assets by net exchange inflow.
        """
        # Pre-defined list of major assets to check
        major_assets = [
            "bitcoin", "ethereum", "ripple", "cardano", "solana",
            "polkadot", "avalanche", "polygon", "chainlink", "uniswap"
        ]

        import asyncio
        results = await asyncio.gather(
            *[tracker.get_exchange_flow_analysis(slug, days=7) for slug in major_assets],
            return_exceptions=True,
        )

        assets_with_flows = []
        for slug, result in zip(major_assets, results):
            if not isinstance(result, Exception) and result.signal == "bearish":
                assets_with_flows.append({
                    "asset": slug,
                    "net_inflow": result.net_flow,
                    "signal_strength": result.signal_strength.value,
                    "interpretation": result.interpretation,
                })

        # Sort by net inflow (highest = most bearish)
        assets_with_flows.sort(key=lambda x: x["net_inflow"], reverse=True)

        return {
            "bearish_assets": assets_with_flows,
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    @app.get("/leaderboard/bullish")
    async def get_bullish_leaderboard(
        tracker: WhaleTracker = Depends(get_tracker),
    ):
        """
        Get assets with the most bullish whale signals.

        Shows top assets by net exchange outflow (accumulation).
        """
        major_assets = [
            "bitcoin", "ethereum", "ripple", "cardano", "solana",
            "polkadot", "avalanche", "polygon", "chainlink", "uniswap"
        ]

        import asyncio
        results = await asyncio.gather(
            *[tracker.get_exchange_flow_analysis(slug, days=7) for slug in major_assets],
            return_exceptions=True,
        )

        assets_with_flows = []
        for slug, result in zip(major_assets, results):
            if not isinstance(result, Exception) and result.signal == "bullish":
                assets_with_flows.append({
                    "asset": slug,
                    "net_outflow": abs(result.net_flow),
                    "signal_strength": result.signal_strength.value,
                    "interpretation": result.interpretation,
                })

        # Sort by net outflow (highest = most bullish)
        assets_with_flows.sort(key=lambda x: x["net_outflow"], reverse=True)

        return {
            "bullish_assets": assets_with_flows,
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    @app.on_event("shutdown")
    async def shutdown():
        """Cleanup on shutdown."""
        global _client, _alert_engine
        if _alert_engine:
            await _alert_engine.stop_monitoring()
        if _client:
            await _client.__aexit__(None, None, None)

    return app


# Create default app instance
app = create_whale_watch_app()
