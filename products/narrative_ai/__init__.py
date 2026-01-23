"""
AI Market Narrative Analyzer
============================

LLM-powered market analysis that combines:
- Trending social topics
- Sentiment analysis
- Whale movements
- Price action

To generate human-readable market narratives explaining
why prices are moving and what might happen next.
"""

from .analyzer import NarrativeAnalyzer
from .prompts import NarrativePrompts
from .api import create_narrative_app

__all__ = ["NarrativeAnalyzer", "NarrativePrompts", "create_narrative_app"]
