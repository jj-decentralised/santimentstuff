"""
Santiment Platform Core
=======================

Core module providing unified access to Santiment API with caching,
rate limiting, and shared utilities for all products.

Products:
- Whale Watch Dashboard
- Social Sentiment Trading Bot
- Project Health Score API
- AI Market Narrative Analyzer
- Research Terminal
"""

from .client import SantimentClient
from .cache import CacheManager
from .models import (
    Asset,
    Metric,
    TimeseriesData,
    HealthScore,
    WhaleTransaction,
    SentimentData,
    NarrativeInsight,
)

__all__ = [
    "SantimentClient",
    "CacheManager",
    "Asset",
    "Metric",
    "TimeseriesData",
    "HealthScore",
    "WhaleTransaction",
    "SentimentData",
    "NarrativeInsight",
]
