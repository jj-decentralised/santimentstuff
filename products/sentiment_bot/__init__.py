"""
Social Sentiment Trading Bot
============================

Automated trading signal generation based on social sentiment analysis.

Features:
- Sentiment-based buy/sell signals
- Contrarian strategy (buy fear, sell greed)
- Backtesting engine
- Risk management
- Exchange integration ready
"""

from .strategy import SentimentStrategy, StrategyConfig
from .signals import SignalGenerator
from .backtest import Backtester
from .api import create_sentiment_bot_app

__all__ = [
    "SentimentStrategy",
    "StrategyConfig",
    "SignalGenerator",
    "Backtester",
    "create_sentiment_bot_app",
]
