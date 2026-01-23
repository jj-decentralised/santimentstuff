"""
Whale Watching Dashboard
========================

Real-time tracking of large holder (whale) movements including:
- Exchange deposit/withdrawal monitoring
- Large transaction alerts
- Whale wallet tracking
- Historical whale behavior analysis
"""

from .tracker import WhaleTracker
from .alerts import WhaleAlertEngine
from .api import create_whale_watch_app

__all__ = ["WhaleTracker", "WhaleAlertEngine", "create_whale_watch_app"]
