"""
Derived / precalculated metrics engine.

Computes higher-order analytics from raw Santiment time-series data stored
in SQLite.  Every function works on plain lists of floats so they stay
testable without a database connection.

Metrics produced
────────────────
Price-derived
  • volatility_30d / _90d   – annualised std-dev of daily log returns
  • sharpe_90d               – 90-day return / 90-day volatility (annualised)
  • max_drawdown_90d         – deepest peak-to-trough drop in last 90 days
  • ma50_distance            – % price is above/below 50-day SMA
  • ma200_distance           – % price is above/below 200-day SMA
  • rsi_14                   – 14-day Relative Strength Index
  • beta_btc_90d             – 90-day beta vs Bitcoin

On-chain derived
  • mvrv_zscore              – (MVRV − 1yr mean) / 1yr std
  • nvt_signal               – 90-day simple moving average of NVT
  • net_exchange_flow_7d     – sum(inflow − outflow) over last 7 days
  • network_value_per_addr   – mcap / DAA
  • dev_intensity             – dev_activity / sqrt(mcap in $M)
  • supply_shock              – supply_outside / supply_on_exchanges

Composite scores  (0–100 scale)
  • momentum_score  – price trend + volume trend + DAA growth
  • value_score     – MVRV zone + NVT zone + exchange outflow
  • risk_score      – volatility + exchange inflow pressure + drawdown
  • health_score    – DAA + dev + network_growth + MVRV
"""

from __future__ import annotations

import math
import statistics
from typing import Optional


# ── helpers ──────────────────────────────────────────────────

def _returns(prices: list[float]) -> list[float]:
    """Daily simple returns from a price series."""
    return [(prices[i] / prices[i - 1] - 1)
            for i in range(1, len(prices))
            if prices[i - 1] and prices[i - 1] != 0]


def _log_returns(prices: list[float]) -> list[float]:
    """Daily log returns from a price series."""
    out = []
    for i in range(1, len(prices)):
        if prices[i] and prices[i] > 0 and prices[i - 1] and prices[i - 1] > 0:
            out.append(math.log(prices[i] / prices[i - 1]))
    return out


def _sma(values: list[float], window: int) -> Optional[float]:
    """Simple moving average of the last `window` values."""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _percentile_rank(value: float, lo: float, hi: float) -> float:
    """Map value into 0-100 between lo and hi."""
    if hi == lo:
        return 50.0
    return _clamp((value - lo) / (hi - lo) * 100, 0, 100)


# ══════════════════════════════════════════════════════════════
# PRICE-DERIVED METRICS
# ══════════════════════════════════════════════════════════════

def volatility(prices: list[float], window: int = 30) -> Optional[float]:
    """Annualised volatility (std-dev of log returns × √365)."""
    tail = prices[-window:] if len(prices) >= window else prices
    lr = _log_returns(tail)
    if len(lr) < 5:
        return None
    return statistics.stdev(lr) * math.sqrt(365)


def sharpe_ratio(prices: list[float], window: int = 90, risk_free: float = 0.0) -> Optional[float]:
    """Annualised Sharpe ratio over `window` days (assumes 0 risk-free)."""
    tail = prices[-window:] if len(prices) >= window else prices
    lr = _log_returns(tail)
    if len(lr) < 10:
        return None
    mean_r = statistics.mean(lr)
    std_r = statistics.stdev(lr)
    if std_r == 0:
        return None
    return (mean_r - risk_free / 365) / std_r * math.sqrt(365)


def max_drawdown(prices: list[float], window: int = 90) -> Optional[float]:
    """Maximum drawdown (%) in last `window` days. Returns negative number."""
    tail = prices[-window:] if len(prices) >= window else prices
    if len(tail) < 2:
        return None
    peak = tail[0]
    worst = 0.0
    for p in tail:
        if p > peak:
            peak = p
        dd = (p - peak) / peak if peak > 0 else 0
        if dd < worst:
            worst = dd
    return round(worst * 100, 2)


def ma_distance(prices: list[float], window: int = 50) -> Optional[float]:
    """% distance of latest price from SMA. Positive = above MA."""
    if len(prices) < window:
        return None
    ma = _sma(prices, window)
    if ma is None or ma == 0:
        return None
    return round((prices[-1] / ma - 1) * 100, 2)


def rsi(prices: list[float], period: int = 14) -> Optional[float]:
    """Relative Strength Index (Wilder smoothing)."""
    if len(prices) < period + 1:
        return None
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(0, c) for c in changes]
    losses = [max(0, -c) for c in changes]

    # Initial averages
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder smoothing
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def beta_vs_btc(token_prices: list[float], btc_prices: list[float],
                window: int = 90) -> Optional[float]:
    """90-day beta vs Bitcoin (covariance / BTC variance)."""
    n = min(window, len(token_prices), len(btc_prices))
    if n < 20:
        return None
    tr = _returns(token_prices[-n:])
    br = _returns(btc_prices[-n:])
    n2 = min(len(tr), len(br))
    if n2 < 10:
        return None
    tr = tr[-n2:]
    br = br[-n2:]
    mean_t = statistics.mean(tr)
    mean_b = statistics.mean(br)
    cov = sum((tr[i] - mean_t) * (br[i] - mean_b) for i in range(n2)) / n2
    var_b = sum((br[i] - mean_b) ** 2 for i in range(n2)) / n2
    if var_b == 0:
        return None
    return round(cov / var_b, 2)


# ══════════════════════════════════════════════════════════════
# ON-CHAIN DERIVED METRICS
# ══════════════════════════════════════════════════════════════

def mvrv_zscore(mvrv_values: list[float], window: int = 365) -> Optional[float]:
    """Z-score of latest MVRV vs its trailing `window`-day distribution."""
    if len(mvrv_values) < 30:
        return None
    tail = mvrv_values[-window:] if len(mvrv_values) >= window else mvrv_values
    if len(tail) < 20:
        return None
    mean_v = statistics.mean(tail)
    std_v = statistics.stdev(tail)
    if std_v == 0:
        return None
    return round((mvrv_values[-1] - mean_v) / std_v, 2)


def nvt_signal(nvt_values: list[float], window: int = 90) -> Optional[float]:
    """90-day simple moving average of NVT — less noisy signal."""
    return round(_sma(nvt_values, window), 2) if _sma(nvt_values, window) is not None else None


def net_exchange_flow_7d(inflow_values: list[float],
                         outflow_values: list[float]) -> Optional[float]:
    """Net exchange flow over last 7 days (positive = flowing IN to exchanges)."""
    n = min(7, len(inflow_values), len(outflow_values))
    if n < 1:
        return None
    total = 0.0
    for i in range(-n, 0):
        inf = inflow_values[i] if inflow_values[i] else 0
        out = outflow_values[i] if outflow_values[i] else 0
        total += inf - out
    return round(total, 2)


def network_value_per_address(mcap: float, daa: float) -> Optional[float]:
    """Market cap per daily active address — usage efficiency."""
    if not daa or daa < 1 or not mcap:
        return None
    return round(mcap / daa, 2)


def dev_intensity(dev_activity_val: float, mcap: float) -> Optional[float]:
    """Dev activity normalised by sqrt of market cap in $M."""
    if not dev_activity_val or not mcap or mcap < 1e6:
        return None
    return round(dev_activity_val / math.sqrt(mcap / 1e6), 2)


def supply_shock_ratio(supply_outside: float, supply_on: float) -> Optional[float]:
    """Ratio of supply outside exchanges to supply on exchanges."""
    if not supply_on or supply_on <= 0 or not supply_outside:
        return None
    return round(supply_outside / supply_on, 2)


# ══════════════════════════════════════════════════════════════
# COMPOSITE SCORES (0–100)
# ══════════════════════════════════════════════════════════════

def momentum_score(
    price_change_7d: Optional[float] = None,
    price_change_30d: Optional[float] = None,
    volume_change: Optional[float] = None,
    daa_change: Optional[float] = None,
    rsi_val: Optional[float] = None,
    ma50_dist: Optional[float] = None,
) -> Optional[float]:
    """
    Composite momentum score (0–100).
    Weights: price trend 35%, volume 20%, DAA 20%, RSI 15%, MA distance 10%.
    """
    components = []
    weights = []

    if price_change_7d is not None and price_change_30d is not None:
        # Blend short and medium term, map -30..+30% → 0..100
        blended = price_change_7d * 0.4 + price_change_30d * 0.6
        components.append(_percentile_rank(blended, -30, 30))
        weights.append(0.35)

    if volume_change is not None:
        components.append(_percentile_rank(volume_change, -50, 100))
        weights.append(0.20)

    if daa_change is not None:
        components.append(_percentile_rank(daa_change, -30, 30))
        weights.append(0.20)

    if rsi_val is not None:
        # RSI already 0-100; center at 50 = neutral
        components.append(rsi_val)
        weights.append(0.15)

    if ma50_dist is not None:
        components.append(_percentile_rank(ma50_dist, -20, 20))
        weights.append(0.10)

    if not components:
        return None
    total_w = sum(weights)
    return round(sum(c * w for c, w in zip(components, weights)) / total_w, 1)


def value_score(
    mvrv: Optional[float] = None,
    mvrv_z: Optional[float] = None,
    nvt_val: Optional[float] = None,
    exchange_balance_change: Optional[float] = None,
) -> Optional[float]:
    """
    Composite value score (0–100).  Higher = more undervalued.
    Inverted: low MVRV & low NVT = high score.
    """
    components = []
    weights = []

    if mvrv is not None:
        # MVRV 0.5 → 100 (deep value), 3.5 → 0 (overvalued)
        components.append(_clamp((3.5 - mvrv) / 3.0 * 100, 0, 100))
        weights.append(0.35)

    if mvrv_z is not None:
        # Z-score < -1 → 100, > +2 → 0
        components.append(_clamp((-mvrv_z + 2) / 3.0 * 100, 0, 100))
        weights.append(0.25)

    if nvt_val is not None:
        # Low NVT = efficient network → higher value score
        components.append(_clamp((150 - nvt_val) / 130 * 100, 0, 100))
        weights.append(0.25)

    if exchange_balance_change is not None:
        # Negative exchange balance change = outflow = accumulation = bullish value
        components.append(_percentile_rank(-exchange_balance_change, -5, 5))
        weights.append(0.15)

    if not components:
        return None
    total_w = sum(weights)
    return round(sum(c * w for c, w in zip(components, weights)) / total_w, 1)


def risk_score(
    vol_30d: Optional[float] = None,
    vol_90d: Optional[float] = None,
    drawdown_90d: Optional[float] = None,
    exchange_inflow_change: Optional[float] = None,
    beta: Optional[float] = None,
) -> Optional[float]:
    """
    Composite risk score (0–100).  Higher = riskier.
    """
    components = []
    weights = []

    if vol_30d is not None:
        # 0% vol → 0, 200%+ annualised → 100
        components.append(_percentile_rank(vol_30d * 100, 0, 200))
        weights.append(0.30)

    if vol_90d is not None:
        components.append(_percentile_rank(vol_90d * 100, 0, 200))
        weights.append(0.15)

    if drawdown_90d is not None:
        # drawdown is negative; -50% → risk 100, 0% → risk 0
        components.append(_percentile_rank(abs(drawdown_90d), 0, 50))
        weights.append(0.25)

    if exchange_inflow_change is not None:
        # Rising inflows → more risk
        components.append(_percentile_rank(exchange_inflow_change, -10, 30))
        weights.append(0.15)

    if beta is not None:
        # High beta → riskier
        components.append(_percentile_rank(beta, 0, 2.5))
        weights.append(0.15)

    if not components:
        return None
    total_w = sum(weights)
    return round(sum(c * w for c, w in zip(components, weights)) / total_w, 1)


def health_score(
    daa_change: Optional[float] = None,
    dev_change: Optional[float] = None,
    growth_change: Optional[float] = None,
    mvrv: Optional[float] = None,
    vol_mcap_ratio: Optional[float] = None,
) -> Optional[float]:
    """
    Composite network health score (0–100).  Higher = healthier.
    """
    components = []
    weights = []

    if daa_change is not None:
        components.append(_percentile_rank(daa_change, -20, 20))
        weights.append(0.30)

    if dev_change is not None:
        components.append(_percentile_rank(dev_change, -30, 30))
        weights.append(0.25)

    if growth_change is not None:
        components.append(_percentile_rank(growth_change, -20, 20))
        weights.append(0.20)

    if mvrv is not None:
        # Healthy MVRV ~1.0–2.0, penalise extremes
        dist = abs(mvrv - 1.5)
        components.append(_clamp((3 - dist) / 3 * 100, 0, 100))
        weights.append(0.15)

    if vol_mcap_ratio is not None:
        # Moderate liquidity is healthy, 5-15% ideal
        dist = abs(vol_mcap_ratio * 100 - 10)
        components.append(_clamp((30 - dist) / 30 * 100, 0, 100))
        weights.append(0.10)

    if not components:
        return None
    total_w = sum(weights)
    return round(sum(c * w for c, w in zip(components, weights)) / total_w, 1)


# ══════════════════════════════════════════════════════════════
# BATCH COMPUTATION — compute all derived metrics for one token
# ══════════════════════════════════════════════════════════════

def compute_token_derived(
    price_series: list[float],
    btc_price_series: list[float] | None = None,
    mvrv_series: list[float] | None = None,
    nvt_series: list[float] | None = None,
    inflow_series: list[float] | None = None,
    outflow_series: list[float] | None = None,
    mcap: float | None = None,
    daa: float | None = None,
    dev_activity_val: float | None = None,
    supply_on: float | None = None,
    supply_outside: float | None = None,
    # Change metrics (already computed in bulk builder)
    price_change_7d: float | None = None,
    price_change_30d: float | None = None,
    volume_change: float | None = None,
    daa_change: float | None = None,
    dev_change: float | None = None,
    growth_change: float | None = None,
    exchange_balance_change: float | None = None,
    vol_mcap_ratio: float | None = None,
) -> dict:
    """
    Compute all derived metrics for a single token.
    Returns a flat dict of metric_name → value (or None).
    """
    result: dict[str, Optional[float]] = {}

    # Price-derived
    result["volatility_30d"] = volatility(price_series, 30) if len(price_series) >= 30 else None
    result["volatility_90d"] = volatility(price_series, 90) if len(price_series) >= 90 else None
    result["sharpe_90d"] = sharpe_ratio(price_series, 90) if len(price_series) >= 90 else None
    result["max_drawdown_90d"] = max_drawdown(price_series, 90) if len(price_series) >= 30 else None
    result["ma50_distance"] = ma_distance(price_series, 50)
    result["ma200_distance"] = ma_distance(price_series, 200)
    result["rsi_14"] = rsi(price_series, 14) if len(price_series) >= 15 else None
    result["beta_btc_90d"] = beta_vs_btc(price_series, btc_price_series, 90) if btc_price_series else None

    # On-chain derived
    result["mvrv_zscore"] = mvrv_zscore(mvrv_series) if mvrv_series and len(mvrv_series) >= 30 else None
    result["nvt_signal"] = nvt_signal(nvt_series) if nvt_series and len(nvt_series) >= 30 else None
    result["net_exchange_flow_7d"] = net_exchange_flow_7d(inflow_series or [], outflow_series or [])
    result["network_value_per_addr"] = network_value_per_address(mcap or 0, daa or 0)
    result["dev_intensity"] = dev_intensity(dev_activity_val or 0, mcap or 0)
    result["supply_shock"] = supply_shock_ratio(supply_outside or 0, supply_on or 0)

    # Composite scores
    result["momentum_score"] = momentum_score(
        price_change_7d=price_change_7d,
        price_change_30d=price_change_30d,
        volume_change=volume_change,
        daa_change=daa_change,
        rsi_val=result["rsi_14"],
        ma50_dist=result["ma50_distance"],
    )
    result["value_score"] = value_score(
        mvrv=mvrv_series[-1] if mvrv_series else None,
        mvrv_z=result["mvrv_zscore"],
        nvt_val=nvt_series[-1] if nvt_series else None,
        exchange_balance_change=exchange_balance_change,
    )
    result["risk_score"] = risk_score(
        vol_30d=result["volatility_30d"],
        vol_90d=result["volatility_90d"],
        drawdown_90d=result["max_drawdown_90d"],
        beta=result["beta_btc_90d"],
    )
    result["health_score"] = health_score(
        daa_change=daa_change,
        dev_change=dev_change,
        growth_change=growth_change,
        mvrv=mvrv_series[-1] if mvrv_series else None,
        vol_mcap_ratio=vol_mcap_ratio,
    )

    return result
