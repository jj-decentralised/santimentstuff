"""
Research Terminal
=================

Unified research interface combining all Santiment-powered products:
- Health Score Analysis
- Whale Tracking
- Sentiment Trading Signals
- AI Narratives
- Custom Metric Explorer

Designed as a Bloomberg Terminal-style interface for crypto research.
"""

from .terminal import ResearchTerminal
from .screener import AssetScreener
from .api import create_terminal_app

__all__ = ["ResearchTerminal", "AssetScreener", "create_terminal_app"]
