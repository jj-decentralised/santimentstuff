"""
Backtesting Engine

Historical backtesting for sentiment-based trading strategies.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from core.client import SantimentClient
from core.models import TradingSignal
from .strategy import SentimentStrategy, StrategyConfig


@dataclass
class Trade:
    """A single backtest trade."""
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    signal_type: str  # "BUY" or "SELL"
    signal_strength: float
    sentiment_at_entry: float

    # Results (filled when closed)
    pnl_percent: Optional[float] = None
    pnl_absolute: Optional[float] = None
    exit_reason: Optional[str] = None  # "take_profit", "stop_loss", "signal", "end"

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    @property
    def is_winner(self) -> bool:
        if self.pnl_percent is None:
            return False
        return self.pnl_percent > 0

    def to_dict(self) -> dict:
        return {
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "signal_type": self.signal_type,
            "signal_strength": self.signal_strength,
            "sentiment_at_entry": self.sentiment_at_entry,
            "pnl_percent": self.pnl_percent,
            "pnl_absolute": self.pnl_absolute,
            "exit_reason": self.exit_reason,
            "is_winner": self.is_winner,
        }


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    asset_slug: str
    start_date: datetime
    end_date: datetime
    strategy_config: StrategyConfig

    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float

    # Return statistics
    total_return_percent: float
    avg_return_per_trade: float
    best_trade_percent: float
    worst_trade_percent: float

    # Risk statistics
    max_drawdown_percent: float
    sharpe_ratio: Optional[float]
    profit_factor: Optional[float]

    # Time statistics
    avg_trade_duration_hours: float
    longest_trade_hours: float

    # Individual trades
    trades: list[Trade] = field(default_factory=list)

    # Equity curve
    equity_curve: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "asset": self.asset_slug,
            "period": {
                "start": self.start_date.isoformat(),
                "end": self.end_date.isoformat(),
            },
            "strategy": {
                "type": self.strategy_config.strategy_type.value,
                "buy_threshold": self.strategy_config.buy_threshold,
                "sell_threshold": self.strategy_config.sell_threshold,
            },
            "statistics": {
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "win_rate": round(self.win_rate * 100, 1),
            },
            "returns": {
                "total_return_percent": round(self.total_return_percent, 2),
                "avg_per_trade": round(self.avg_return_per_trade, 2),
                "best_trade": round(self.best_trade_percent, 2),
                "worst_trade": round(self.worst_trade_percent, 2),
            },
            "risk": {
                "max_drawdown_percent": round(self.max_drawdown_percent, 2),
                "sharpe_ratio": round(self.sharpe_ratio, 2) if self.sharpe_ratio else None,
                "profit_factor": round(self.profit_factor, 2) if self.profit_factor else None,
            },
            "timing": {
                "avg_trade_duration_hours": round(self.avg_trade_duration_hours, 1),
                "longest_trade_hours": round(self.longest_trade_hours, 1),
            },
            "trades": [t.to_dict() for t in self.trades],
            "equity_curve": self.equity_curve,
        }


class Backtester:
    """
    Backtesting engine for sentiment trading strategies.

    Simulates trading based on historical sentiment and price data.
    """

    def __init__(
        self,
        client: SantimentClient,
        initial_capital: float = 10000.0,
    ):
        self.client = client
        self.initial_capital = initial_capital

    async def run_backtest(
        self,
        asset_slug: str,
        start_date: datetime,
        end_date: datetime,
        config: Optional[StrategyConfig] = None,
    ) -> BacktestResult:
        """
        Run a backtest for the given period.

        Args:
            asset_slug: Asset to backtest
            start_date: Backtest start date
            end_date: Backtest end date
            config: Strategy configuration (uses default if None)

        Returns:
            BacktestResult with full statistics and trade history
        """
        config = config or StrategyConfig()
        strategy = SentimentStrategy(config)

        # Fetch historical data
        sentiment_data, price_data = await asyncio.gather(
            self.client.get_sentiment(asset_slug, start_date, end_date, "1d"),
            self.client.get_price(asset_slug, start_date, end_date, "1d"),
        )

        if not sentiment_data or not price_data:
            raise ValueError(f"Insufficient data for {asset_slug}")

        # Create price lookup
        price_map = {
            datetime.fromisoformat(p["datetime"].replace("Z", "+00:00")).date(): p
            for p in price_data
        }

        # Initialize tracking
        trades: list[Trade] = []
        equity = self.initial_capital
        equity_curve = [{"date": start_date.isoformat(), "equity": equity}]
        current_trade: Optional[Trade] = None
        peak_equity = equity

        # Process each day
        sentiment_window = []

        for sentiment in sentiment_data:
            date = sentiment.datetime.date()
            price_info = price_map.get(date)

            if not price_info:
                continue

            current_price = price_info.get("closePriceUsd", 0)
            if current_price <= 0:
                continue

            # Update sentiment window for strategy
            sentiment_window.append(sentiment)
            if len(sentiment_window) > config.lookback_periods:
                sentiment_window = sentiment_window[-config.lookback_periods:]

            # Check existing trade for exit conditions
            if current_trade and not current_trade.is_open:
                pass  # Already closed
            elif current_trade:
                exit_reason = self._check_exit_conditions(
                    current_trade, current_price, config
                )
                if exit_reason:
                    current_trade = self._close_trade(
                        current_trade, current_price, sentiment.datetime, exit_reason
                    )
                    # Update equity
                    equity *= (1 + current_trade.pnl_percent / 100)
                    trades.append(current_trade)
                    current_trade = None

            # Generate new signal if no position
            if current_trade is None and len(sentiment_window) >= config.confirmation_periods:
                signal = strategy.generate_signal(
                    asset_slug, sentiment_window, current_price
                )

                if signal and signal.is_actionable:
                    current_trade = Trade(
                        entry_time=sentiment.datetime,
                        exit_time=None,
                        entry_price=current_price,
                        exit_price=None,
                        signal_type=signal.signal_type,
                        signal_strength=signal.strength,
                        sentiment_at_entry=sentiment.sentiment_weighted,
                    )

            # Update equity curve
            if current_trade:
                # Mark-to-market
                unrealized_pnl = self._calculate_pnl(
                    current_trade.signal_type,
                    current_trade.entry_price,
                    current_price
                )
                marked_equity = equity * (1 + unrealized_pnl / 100)
            else:
                marked_equity = equity

            equity_curve.append({
                "date": sentiment.datetime.isoformat(),
                "equity": round(marked_equity, 2),
            })

            # Track peak for drawdown
            peak_equity = max(peak_equity, marked_equity)

        # Close any remaining trade at end
        if current_trade:
            final_price = price_data[-1].get("closePriceUsd", current_trade.entry_price)
            current_trade = self._close_trade(
                current_trade, final_price, end_date, "end"
            )
            equity *= (1 + current_trade.pnl_percent / 100)
            trades.append(current_trade)

        # Calculate statistics
        return self._calculate_statistics(
            asset_slug, start_date, end_date, config,
            trades, equity, equity_curve
        )

    def _check_exit_conditions(
        self,
        trade: Trade,
        current_price: float,
        config: StrategyConfig,
    ) -> Optional[str]:
        """Check if trade should be exited."""
        pnl = self._calculate_pnl(trade.signal_type, trade.entry_price, current_price)

        # Check stop loss
        if pnl <= -config.stop_loss_percent:
            return "stop_loss"

        # Check take profit
        if pnl >= config.take_profit_percent:
            return "take_profit"

        return None

    def _calculate_pnl(
        self,
        signal_type: str,
        entry_price: float,
        current_price: float,
    ) -> float:
        """Calculate PnL percentage."""
        if signal_type == "BUY":
            return (current_price - entry_price) / entry_price * 100
        else:
            return (entry_price - current_price) / entry_price * 100

    def _close_trade(
        self,
        trade: Trade,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str,
    ) -> Trade:
        """Close a trade and calculate final PnL."""
        pnl_percent = self._calculate_pnl(trade.signal_type, trade.entry_price, exit_price)

        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.pnl_percent = pnl_percent
        trade.pnl_absolute = trade.entry_price * (pnl_percent / 100)
        trade.exit_reason = exit_reason

        return trade

    def _calculate_statistics(
        self,
        asset_slug: str,
        start_date: datetime,
        end_date: datetime,
        config: StrategyConfig,
        trades: list[Trade],
        final_equity: float,
        equity_curve: list[dict],
    ) -> BacktestResult:
        """Calculate backtest statistics."""

        if not trades:
            return BacktestResult(
                asset_slug=asset_slug,
                start_date=start_date,
                end_date=end_date,
                strategy_config=config,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0,
                total_return_percent=0,
                avg_return_per_trade=0,
                best_trade_percent=0,
                worst_trade_percent=0,
                max_drawdown_percent=0,
                sharpe_ratio=None,
                profit_factor=None,
                avg_trade_duration_hours=0,
                longest_trade_hours=0,
                trades=[],
                equity_curve=equity_curve,
            )

        # Basic counts
        winning_trades = [t for t in trades if t.is_winner]
        losing_trades = [t for t in trades if not t.is_winner]

        # Returns
        returns = [t.pnl_percent for t in trades]
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        # Durations
        durations = []
        for t in trades:
            if t.exit_time:
                duration = (t.exit_time - t.entry_time).total_seconds() / 3600
                durations.append(duration)

        # Max drawdown
        max_drawdown = 0
        peak = equity_curve[0]["equity"]
        for point in equity_curve:
            eq = point["equity"]
            peak = max(peak, eq)
            drawdown = (peak - eq) / peak * 100
            max_drawdown = max(max_drawdown, drawdown)

        # Sharpe ratio (annualized, assuming daily returns)
        if len(returns) > 1:
            returns_std = np.std(returns)
            if returns_std > 0:
                sharpe = (np.mean(returns) / returns_std) * np.sqrt(252)  # Annualized
            else:
                sharpe = None
        else:
            sharpe = None

        # Profit factor
        gross_profit = sum(t.pnl_percent for t in winning_trades)
        gross_loss = abs(sum(t.pnl_percent for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        return BacktestResult(
            asset_slug=asset_slug,
            start_date=start_date,
            end_date=end_date,
            strategy_config=config,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=len(winning_trades) / len(trades) if trades else 0,
            total_return_percent=total_return,
            avg_return_per_trade=np.mean(returns),
            best_trade_percent=max(returns),
            worst_trade_percent=min(returns),
            max_drawdown_percent=max_drawdown,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            avg_trade_duration_hours=np.mean(durations) if durations else 0,
            longest_trade_hours=max(durations) if durations else 0,
            trades=trades,
            equity_curve=equity_curve,
        )

    async def optimize_parameters(
        self,
        asset_slug: str,
        start_date: datetime,
        end_date: datetime,
        param_ranges: Optional[dict] = None,
    ) -> dict:
        """
        Optimize strategy parameters using grid search.

        Args:
            asset_slug: Asset to optimize for
            start_date: Backtest start date
            end_date: Backtest end date
            param_ranges: Dict of parameter ranges to test

        Returns:
            Dict with best parameters and results
        """
        if param_ranges is None:
            param_ranges = {
                "buy_threshold": [-0.2, -0.3, -0.4, -0.5],
                "sell_threshold": [0.3, 0.4, 0.5, 0.6],
                "stop_loss_percent": [3, 5, 7, 10],
                "take_profit_percent": [10, 15, 20, 25],
            }

        best_result = None
        best_params = None
        all_results = []

        # Grid search
        for buy_thresh in param_ranges.get("buy_threshold", [-0.3]):
            for sell_thresh in param_ranges.get("sell_threshold", [0.5]):
                for stop_loss in param_ranges.get("stop_loss_percent", [5]):
                    for take_profit in param_ranges.get("take_profit_percent", [15]):
                        config = StrategyConfig(
                            buy_threshold=buy_thresh,
                            sell_threshold=sell_thresh,
                            stop_loss_percent=stop_loss,
                            take_profit_percent=take_profit,
                        )

                        try:
                            result = await self.run_backtest(
                                asset_slug, start_date, end_date, config
                            )

                            all_results.append({
                                "params": {
                                    "buy_threshold": buy_thresh,
                                    "sell_threshold": sell_thresh,
                                    "stop_loss": stop_loss,
                                    "take_profit": take_profit,
                                },
                                "return": result.total_return_percent,
                                "sharpe": result.sharpe_ratio,
                                "win_rate": result.win_rate,
                                "trades": result.total_trades,
                            })

                            # Optimize for Sharpe ratio if available, else return
                            score = result.sharpe_ratio if result.sharpe_ratio else result.total_return_percent / 10

                            if best_result is None or score > (best_result.sharpe_ratio or -999):
                                best_result = result
                                best_params = config

                        except Exception:
                            continue

        return {
            "best_params": {
                "buy_threshold": best_params.buy_threshold if best_params else None,
                "sell_threshold": best_params.sell_threshold if best_params else None,
                "stop_loss_percent": best_params.stop_loss_percent if best_params else None,
                "take_profit_percent": best_params.take_profit_percent if best_params else None,
            },
            "best_result": best_result.to_dict() if best_result else None,
            "all_results": sorted(all_results, key=lambda x: x.get("sharpe") or -999, reverse=True),
        }
