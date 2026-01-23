"""
Project Health Score API
========================

Composite health scoring system for cryptocurrency projects.
Combines multiple on-chain, social, and development metrics into
a single 0-100 score with component breakdowns.
"""

from .calculator import HealthScoreCalculator
from .api import create_health_score_app

__all__ = ["HealthScoreCalculator", "create_health_score_app"]
