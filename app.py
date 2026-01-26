"""
Smart Money Intelligence - Nansen-Powered Dashboard
A comprehensive trading signals platform powered by Nansen's smart money data.
"""

import os
import json
import httpx
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# ============== SNAPSHOT CACHE ==============
CACHE_DIR = Path("data/snapshots")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ============== CONFIG ==============
NANSEN_BASE_URL = "https://api.nansen.ai/api/v1"
NANSEN_API_KEY = os.environ.get("NANSEN_API_KEY", "5Y12GfD7Y3mbgtKdmZywPqOmGyxlK5eN")

DEFAULT_CHAINS = ["solana", "ethereum", "base", "arbitrum", "polygon"]

# Token quality filters - exclude shitcoins
MIN_MARKET_CAP = 100_000_000  # $100M minimum
MIN_TOKEN_AGE_DAYS = 30  # 30 days minimum


def passes_token_filter(item):
    """Check if token meets quality thresholds (mcap > $100M, age > 30d)."""
    mcap = item.get("market_cap_usd", 0) or 0
    age = item.get("token_age_days", 0) or 0
    return mcap >= MIN_MARKET_CAP and age >= MIN_TOKEN_AGE_DAYS


def nansen_headers():
    return {"apiKey": NANSEN_API_KEY, "Content-Type": "application/json"}

def get_date_range(days=30):
    """Return date range dict for Nansen API."""
    to_date = datetime.now().strftime('%Y-%m-%d')
    from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    return {"from": from_date, "to": to_date}

def time_ago(timestamp_str):
    """Convert timestamp to human-readable time ago."""
    if not timestamp_str:
        return "?"
    try:
        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00').replace('+00:00', ''))
        diff = datetime.now() - ts
        if diff.days > 0:
            return f"{diff.days}d ago"
        hours = diff.seconds // 3600
        if hours > 0:
            return f"{hours}h ago"
        minutes = diff.seconds // 60
        return f"{minutes}m ago" if minutes > 0 else "just now"
    except:
        return "?"


def categorize_trader(label):
    """Categorize a trader/holder based on their Nansen label.

    Returns: (category, emoji, description)
    """
    if not label:
        return ("unknown", "❓", "Unknown Wallet")

    label_lower = label.lower()

    # Exchange detection
    exchanges = ["binance", "okx", "coinbase", "kraken", "robinhood", "bybit",
                 "bitget", "bithumb", "upbit", "btcturk", "gate", "revolut",
                 "crypto.com", "kucoin", "huobi", "ftx"]
    if "🏦" in label or any(ex in label_lower for ex in exchanges):
        return ("exchange", "🏦", "Exchange")

    # Whale/Millionaire detection
    if "millionaire" in label_lower:
        if "token millionaire" in label_lower:
            return ("token_whale", "🐋", "Token Whale")
        elif "eth millionaire" in label_lower:
            return ("eth_whale", "💎", "ETH Whale")
        elif "nft millionaire" in label_lower:
            return ("nft_whale", "🖼️", "NFT Whale")
        return ("whale", "🐋", "Whale")

    # High balance
    if "high balance" in label_lower:
        return ("high_balance", "💰", "High Balance")

    # Smart trader detection
    if "smart" in label_lower:
        return ("smart_trader", "🧠", "Smart Trader")

    # DeFi/Protocol detection
    if "🤖" in label or "uniswap" in label_lower or "aave" in label_lower or \
       "compound" in label_lower or "liquidity pool" in label_lower:
        return ("defi_protocol", "🤖", "DeFi Protocol")

    # Fund detection
    if "fund" in label_lower or "capital" in label_lower or "ventures" in label_lower:
        return ("fund", "🏛️", "Fund/VC")

    # Burn address
    if "burn" in label_lower or "dead" in label_lower:
        return ("burn", "🔥", "Burn Address")

    # Public figure
    if "public figure" in label_lower:
        return ("public_figure", "👤", "Public Figure")

    # Fresh wallet
    if "fresh" in label_lower:
        return ("fresh_wallet", "🆕", "Fresh Wallet")

    # Default - has a label but uncategorized
    return ("labeled", "🏷️", "Labeled Wallet")


# ============== NANSEN API FUNCTIONS ==============

def fetch_smart_money_netflow(chains=None, direction="DESC"):
    """Fetch smart money net flows - pre-aggregated by token.

    Args:
        chains: List of chains to query
        direction: "DESC" for inflows (highest first), "ASC" for outflows (lowest first)
    """
    chains = chains or DEFAULT_CHAINS

    try:
        r = httpx.post(
            f"{NANSEN_BASE_URL}/smart-money/netflow",
            headers=nansen_headers(),
            json={
                "chains": chains,
                "filters": {
                    "include_stablecoins": False,
                    "include_native_tokens": False,
                    "include_smart_money_labels": ["Fund", "Smart Trader", "30D Smart Trader"],
                },
                "pagination": {"page": 1, "per_page": 100},
                "order_by": [{"field": "net_flow_24h_usd", "direction": direction}],
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Netflow error: {e}")
        return {"data": [], "error": str(e)}


def fetch_smart_money_holdings(chains=None):
    """Fetch aggregated token holdings by smart money."""
    chains = chains or DEFAULT_CHAINS

    try:
        r = httpx.post(
            f"{NANSEN_BASE_URL}/smart-money/holdings",
            headers=nansen_headers(),
            json={
                "chains": chains,
                "filters": {
                    "include_smart_money_labels": ["Fund", "Smart Trader", "30D Smart Trader"],
                },
                "pagination": {"page": 1, "per_page": 50},
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Holdings error: {e}")
        return {"data": [], "error": str(e)}


def fetch_smart_money_dex_trades(chains=None):
    """Fetch real-time DEX trades from smart money."""
    chains = chains or DEFAULT_CHAINS

    try:
        r = httpx.post(
            f"{NANSEN_BASE_URL}/smart-money/dex-trades",
            headers=nansen_headers(),
            json={
                "chains": chains,
                "filters": {
                    "include_smart_money_labels": ["Fund", "Smart Trader", "30D Smart Trader"],
                },
                "pagination": {"page": 1, "per_page": 100},
                "order_by": [{"field": "block_timestamp", "direction": "DESC"}],
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"DEX trades error: {e}")
        return {"data": [], "error": str(e)}


def fetch_flow_intelligence(token_address, chain="solana"):
    """Fetch flow intelligence for a token - whale/smart/exchange breakdown."""
    try:
        r = httpx.post(
            f"{NANSEN_BASE_URL}/tgm/flow-intelligence",
            headers=nansen_headers(),
            json={
                "chain": chain,
                "token_address": token_address,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Flow intelligence error: {e}")
        return {"data": [], "error": str(e)}


def fetch_token_holders(token_address, chain="solana", page=1, per_page=30):
    """Fetch token holders - who holds this token and how much."""
    try:
        r = httpx.post(
            f"{NANSEN_BASE_URL}/tgm/holders",
            headers=nansen_headers(),
            json={
                "chain": chain,
                "token_address": token_address,
                "pagination": {"page": page, "per_page": per_page},
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Token holders error: {e}")
        return {"data": [], "error": str(e)}


def fetch_pnl_leaderboard(token_address, chain="solana", days=30):
    """Fetch P/L leaderboard for a token - top traders by profit."""
    try:
        r = httpx.post(
            f"{NANSEN_BASE_URL}/tgm/pnl-leaderboard",
            headers=nansen_headers(),
            json={
                "chain": chain,
                "token_address": token_address,
                "date": get_date_range(days),
                "pagination": {"page": 1, "per_page": 20},
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"P/L leaderboard error: {e}")
        return {"data": [], "error": str(e)}


def fetch_trader_pnl(address, chain="solana", days=30):
    """Fetch P/L summary for a specific trader."""
    try:
        r = httpx.post(
            f"{NANSEN_BASE_URL}/profiler/address/pnl-summary",
            headers=nansen_headers(),
            json={
                "chain": chain,
                "address": address,
                "date": get_date_range(days),
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Trader P/L error: {e}")
        return {"error": str(e)}


def fetch_trader_transactions(address, chain="solana", days=30):
    """Fetch transaction history for a trader."""
    try:
        r = httpx.post(
            f"{NANSEN_BASE_URL}/profiler/address/transactions",
            headers=nansen_headers(),
            json={
                "chain": chain,
                "address": address,
                "date": get_date_range(days),
                "pagination": {"page": 1, "per_page": 50},
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Trader transactions error: {e}")
        return {"data": [], "error": str(e)}


# ============== TOKEN SEARCH (via CoinGecko) ==============

# Chain mapping from CoinGecko platform names to Nansen chain names
COINGECKO_TO_NANSEN_CHAIN = {
    "ethereum": "ethereum",
    "solana": "solana",
    "base": "base",
    "arbitrum-one": "arbitrum",
    "polygon-pos": "polygon",
    "optimistic-ethereum": "optimism",
    "binance-smart-chain": "bsc",
    "avalanche": "avalanche",
}


def lookup_token_by_symbol(symbol):
    """Search for token by symbol using CoinGecko and return contract addresses.

    Returns:
        dict with name, symbol, and addresses by chain, or None if not found
    """
    try:
        # Search for the token
        search_resp = httpx.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": symbol},
            timeout=10,
        )
        search_resp.raise_for_status()
        coins = search_resp.json().get("coins", [])

        # Find exact symbol match (case-insensitive)
        matching_coin = None
        for coin in coins:
            if coin.get("symbol", "").upper() == symbol.upper():
                matching_coin = coin
                break

        if not matching_coin:
            # Try first result if no exact match
            if coins:
                matching_coin = coins[0]
            else:
                return None

        # Get full coin details including contract addresses
        coin_id = matching_coin["id"]
        detail_resp = httpx.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}",
            params={"localization": "false", "tickers": "false", "market_data": "true", "community_data": "false", "developer_data": "false"},
            timeout=15,
        )
        detail_resp.raise_for_status()
        detail = detail_resp.json()

        # Extract contract addresses per chain
        platforms = detail.get("platforms", {})
        addresses = {}
        for cg_chain, address in platforms.items():
            if address and cg_chain in COINGECKO_TO_NANSEN_CHAIN:
                nansen_chain = COINGECKO_TO_NANSEN_CHAIN[cg_chain]
                addresses[nansen_chain] = address

        # Get market data
        market_data = detail.get("market_data", {})

        return {
            "id": coin_id,
            "name": detail.get("name", matching_coin.get("name", "")),
            "symbol": detail.get("symbol", matching_coin.get("symbol", "")).upper(),
            "addresses": addresses,
            "market_cap_usd": market_data.get("market_cap", {}).get("usd", 0),
            "price_usd": market_data.get("current_price", {}).get("usd", 0),
            "price_change_24h": market_data.get("price_change_percentage_24h", 0),
            "image": detail.get("image", {}).get("small", ""),
        }

    except Exception as e:
        print(f"CoinGecko lookup error for {symbol}: {e}")
        return None


# ============== DEEP INTELLIGENCE FUNCTIONS ==============

def save_daily_snapshot():
    """Save daily snapshot of smart money flows for historical analysis."""
    today = datetime.now().strftime("%Y-%m-%d")
    snapshot_path = CACHE_DIR / f"flows_{today}.json"

    # Skip if already saved today
    if snapshot_path.exists():
        return {"status": "already_exists", "date": today}

    try:
        # Fetch current flows
        flows_data = fetch_smart_money_netflow(direction="DESC")
        holdings_data = fetch_smart_money_holdings()

        snapshot = {
            "date": today,
            "timestamp": datetime.now().isoformat(),
            "flows": flows_data.get("data", []),
            "holdings": holdings_data.get("data", []),
        }

        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f)

        return {"status": "saved", "date": today, "tokens": len(snapshot["flows"])}
    except Exception as e:
        print(f"Snapshot save error: {e}")
        return {"status": "error", "error": str(e)}


def get_historical_flows(token_address, days=30):
    """Get historical flow data for a specific token from cached snapshots."""
    history = []

    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        snapshot_path = CACHE_DIR / f"flows_{date}.json"

        if snapshot_path.exists():
            try:
                with open(snapshot_path) as f:
                    data = json.load(f)
                    for token in data.get("flows", []):
                        if token.get("token_address") == token_address:
                            history.append({
                                "date": date,
                                "flow_24h": token.get("net_flow_24h_usd", 0) or 0,
                                "flow_7d": token.get("net_flow_7d_usd", 0) or 0,
                                "trader_count": token.get("trader_count", 0),
                            })
                            break
            except Exception as e:
                print(f"Error reading snapshot {date}: {e}")

    return sorted(history, key=lambda x: x["date"])


def calculate_accumulation_score(token_data, history=None):
    """Calculate accumulation score (0-100) based on multiple factors.

    Components:
    - Flow Consistency (0-25): Positive flow days / 7 days
    - Holder Growth (0-25): Based on trader count trend
    - Exchange Outflows (0-25): Based on exchange segment flow
    - Stealth Factor (0-25): Volume divergence from price
    """
    score = 0
    breakdown = {}

    # Flow Consistency Score (0-25)
    flow_24h = token_data.get("net_flow_24h_usd", 0) or 0
    flow_7d = token_data.get("net_flow_7d_usd", 0) or 0
    flow_30d = token_data.get("net_flow_30d_usd", 0) or 0

    # Check consistency across timeframes
    positive_timeframes = sum([
        1 if flow_24h > 0 else 0,
        1 if flow_7d > 0 else 0,
        1 if flow_30d > 0 else 0,
    ])
    consistency_score = (positive_timeframes / 3) * 25

    # Bonus for increasing momentum
    if flow_24h > 0 and flow_7d > 0 and flow_24h > (flow_7d / 7):
        consistency_score = min(25, consistency_score + 5)

    breakdown["flow_consistency"] = {
        "score": round(consistency_score, 1),
        "max": 25,
        "detail": f"{positive_timeframes}/3 timeframes positive"
    }
    score += consistency_score

    # Holder Growth Score (0-25)
    trader_count = token_data.get("trader_count", 0) or 0
    if trader_count >= 50:
        holder_score = 25
    elif trader_count >= 20:
        holder_score = 20
    elif trader_count >= 10:
        holder_score = 15
    elif trader_count >= 5:
        holder_score = 10
    else:
        holder_score = 5

    breakdown["holder_growth"] = {
        "score": holder_score,
        "max": 25,
        "detail": f"{trader_count} active traders"
    }
    score += holder_score

    # Exchange Flow Score (0-25) - Negative exchange flow = accumulation
    # This would require flow_intelligence data, estimate from general flow
    if flow_7d > 100000:  # Strong inflow
        exchange_score = 25
    elif flow_7d > 50000:
        exchange_score = 20
    elif flow_7d > 10000:
        exchange_score = 15
    elif flow_7d > 0:
        exchange_score = 10
    else:
        exchange_score = 5

    breakdown["smart_money_conviction"] = {
        "score": exchange_score,
        "max": 25,
        "detail": f"${flow_7d:,.0f} 7d flow"
    }
    score += exchange_score

    # Stealth Factor (0-25) - Strong flow with stable price = stealth accumulation
    price_change = token_data.get("price_change_24h", 0) or 0
    if flow_24h > 50000 and abs(price_change) < 5:
        stealth_score = 25  # High flow, low price change = stealth
    elif flow_24h > 10000 and abs(price_change) < 10:
        stealth_score = 20
    elif flow_24h > 0:
        stealth_score = 15
    else:
        stealth_score = 10

    breakdown["stealth_factor"] = {
        "score": stealth_score,
        "max": 25,
        "detail": f"Flow vs {price_change:.1f}% price change"
    }
    score += stealth_score

    # Determine accumulation phase
    if score >= 80:
        phase = "strong_accumulation"
        phase_label = "Strong Accumulation"
    elif score >= 60:
        phase = "accumulation"
        phase_label = "Accumulation"
    elif score >= 40:
        phase = "neutral"
        phase_label = "Neutral"
    elif score >= 20:
        phase = "distribution"
        phase_label = "Distribution"
    else:
        phase = "strong_distribution"
        phase_label = "Strong Distribution"

    return {
        "score": round(score),
        "max_score": 100,
        "phase": phase,
        "phase_label": phase_label,
        "breakdown": breakdown,
    }


def analyze_entry_quality(pnl_data, current_price=None):
    """Analyze entry quality based on smart money's average entry and profit status.

    Returns assessment of whether it's early, mid, or late to enter.
    """
    if not pnl_data:
        return {"quality": "unknown", "reason": "No P/L data available"}

    traders = pnl_data if isinstance(pnl_data, list) else pnl_data.get("data", [])
    if not traders:
        return {"quality": "unknown", "reason": "No trader data"}

    # Calculate metrics
    total_pnl = sum(t.get("pnl_usd_total", 0) or 0 for t in traders)
    total_realized = sum(t.get("pnl_usd_realised", 0) or 0 for t in traders)
    total_unrealized = sum(t.get("pnl_usd_unrealised", 0) or 0 for t in traders)
    total_holding = sum(t.get("holding_usd", 0) or 0 for t in traders)

    # Count profitable traders
    profitable = sum(1 for t in traders if (t.get("pnl_usd_total", 0) or 0) > 0)
    total_traders = len(traders)
    profit_ratio = profitable / total_traders if total_traders > 0 else 0

    # Calculate profit taken ratio
    if total_pnl > 0:
        profit_taken_ratio = total_realized / total_pnl if total_pnl > 0 else 0
    else:
        profit_taken_ratio = 0

    # Determine entry quality
    if profit_ratio < 0.3:
        quality = "early"
        label = "Early Entry"
        description = "Most smart money still underwater - potential early entry"
    elif profit_ratio < 0.5 and profit_taken_ratio < 0.2:
        quality = "early_mid"
        label = "Early-Mid Stage"
        description = "Smart money building positions, limited profit taking"
    elif profit_ratio < 0.7 and profit_taken_ratio < 0.4:
        quality = "mid"
        label = "Mid Stage"
        description = "Moderate profits, some accumulation continuing"
    elif profit_ratio < 0.85 and profit_taken_ratio < 0.6:
        quality = "late"
        label = "Late Stage"
        description = "Most smart money profitable, consider caution"
    else:
        quality = "very_late"
        label = "Very Late"
        description = "Smart money heavily in profit and taking gains"

    return {
        "quality": quality,
        "label": label,
        "description": description,
        "metrics": {
            "profit_ratio": round(profit_ratio, 2),
            "profitable_traders": profitable,
            "total_traders": total_traders,
            "total_pnl_usd": total_pnl,
            "realized_pnl_usd": total_realized,
            "unrealized_pnl_usd": total_unrealized,
            "profit_taken_ratio": round(profit_taken_ratio, 2),
            "total_holding_usd": total_holding,
        },
    }


def analyze_holder_conviction(holders_data):
    """Analyze holder conviction - diamond hands vs traders.

    Segments holders by their behavior patterns.
    """
    if not holders_data:
        return {"conviction_ratio": 0, "segments": {}}

    holders = holders_data if isinstance(holders_data, list) else holders_data.get("data", [])
    if not holders:
        return {"conviction_ratio": 0, "segments": {}}

    segments = {
        "diamond_hands": {"count": 0, "value_usd": 0, "description": "Long-term holders, minimal selling"},
        "conviction": {"count": 0, "value_usd": 0, "description": "Steady holders with some activity"},
        "active_traders": {"count": 0, "value_usd": 0, "description": "Regular trading activity"},
        "new_entrants": {"count": 0, "value_usd": 0, "description": "Recently entered position"},
    }

    for holder in holders:
        inflow = holder.get("total_inflow", 0) or 0
        outflow = holder.get("total_outflow", 0) or 0
        value_usd = holder.get("value_usd", 0) or 0
        change_30d = holder.get("balance_change_30d", 0) or 0

        # Calculate sell ratio
        sell_ratio = outflow / inflow if inflow > 0 else 0

        # Categorize based on behavior
        if sell_ratio < 0.1 and inflow > 0:
            segments["diamond_hands"]["count"] += 1
            segments["diamond_hands"]["value_usd"] += value_usd
        elif sell_ratio < 0.3:
            segments["conviction"]["count"] += 1
            segments["conviction"]["value_usd"] += value_usd
        elif change_30d > 0 and sell_ratio < 0.5:
            segments["new_entrants"]["count"] += 1
            segments["new_entrants"]["value_usd"] += value_usd
        else:
            segments["active_traders"]["count"] += 1
            segments["active_traders"]["value_usd"] += value_usd

    total_holders = len(holders)
    total_value = sum(s["value_usd"] for s in segments.values())

    # Calculate conviction ratio (diamond_hands + conviction) / total
    conviction_count = segments["diamond_hands"]["count"] + segments["conviction"]["count"]
    conviction_ratio = conviction_count / total_holders if total_holders > 0 else 0

    # Calculate value-weighted conviction
    conviction_value = segments["diamond_hands"]["value_usd"] + segments["conviction"]["value_usd"]
    conviction_value_ratio = conviction_value / total_value if total_value > 0 else 0

    # Determine stability assessment
    if conviction_value_ratio > 0.7:
        stability = "very_stable"
        stability_label = "Very Stable"
    elif conviction_value_ratio > 0.5:
        stability = "stable"
        stability_label = "Stable"
    elif conviction_value_ratio > 0.3:
        stability = "moderate"
        stability_label = "Moderate"
    else:
        stability = "volatile"
        stability_label = "Volatile"

    return {
        "conviction_ratio": round(conviction_ratio, 2),
        "conviction_value_ratio": round(conviction_value_ratio, 2),
        "stability": stability,
        "stability_label": stability_label,
        "total_holders": total_holders,
        "total_value_usd": total_value,
        "segments": segments,
    }


def find_related_tokens(token_address, chain, holders_data=None):
    """Find tokens that share smart money holders with the given token.

    Returns tokens with high holder overlap.
    """
    # This is a simplified version - full implementation would need
    # to query each holder's portfolio, which is API-intensive
    # For now, return based on chain/category patterns

    # Get holders if not provided
    if holders_data is None:
        holders_data = fetch_token_holders(token_address, chain)

    holders = holders_data.get("data", []) if isinstance(holders_data, dict) else holders_data
    if not holders:
        return {"related": [], "note": "No holder data for correlation"}

    # Extract labels to find patterns
    label_patterns = {}
    for holder in holders[:20]:
        label = holder.get("address_label", "")
        if label:
            # Extract potential fund/entity names
            words = label.lower().split()
            for word in words:
                if len(word) > 3 and word not in ["wallet", "token", "smart", "trader"]:
                    label_patterns[word] = label_patterns.get(word, 0) + 1

    # Get top patterns
    top_patterns = sorted(label_patterns.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "holder_patterns": [{"pattern": p[0], "count": p[1]} for p in top_patterns],
        "shared_holder_count": len([h for h in holders if h.get("address_label")]),
        "total_analyzed": len(holders[:20]),
        "note": "Based on holder label analysis. Full correlation requires portfolio queries.",
    }


# Alert thresholds
ALERT_THRESHOLDS = {
    "whale_entry": 500_000,       # Single position > $500K
    "flow_spike": 2.0,            # 24h flow > 2x 7d average
    "accumulation_score_high": 75,  # Score above 75
    "profit_taking_warning": 0.5,   # >50% profit taken
}


def check_alerts(token_data, accumulation_score=None, entry_quality=None):
    """Check for alert conditions on a token."""
    alerts = []

    flow_24h = token_data.get("net_flow_24h_usd", 0) or 0
    flow_7d = token_data.get("net_flow_7d_usd", 0) or 0
    symbol = token_data.get("token_symbol", "???")

    # Whale entry alert
    if flow_24h > ALERT_THRESHOLDS["whale_entry"]:
        alerts.append({
            "type": "whale_entry",
            "severity": "high",
            "title": "Whale Entry Detected",
            "message": f"${flow_24h:,.0f} inflow in 24h",
            "token": symbol,
        })

    # Flow spike alert
    avg_daily_7d = flow_7d / 7 if flow_7d else 0
    if avg_daily_7d > 0 and flow_24h > avg_daily_7d * ALERT_THRESHOLDS["flow_spike"]:
        alerts.append({
            "type": "flow_spike",
            "severity": "medium",
            "title": "Flow Spike",
            "message": f"24h flow is {flow_24h/avg_daily_7d:.1f}x the 7d average",
            "token": symbol,
        })

    # High accumulation score
    if accumulation_score and accumulation_score.get("score", 0) >= ALERT_THRESHOLDS["accumulation_score_high"]:
        alerts.append({
            "type": "strong_accumulation",
            "severity": "high",
            "title": "Strong Accumulation Signal",
            "message": f"Accumulation score: {accumulation_score['score']}/100",
            "token": symbol,
        })

    # Profit taking warning
    if entry_quality:
        profit_taken = entry_quality.get("metrics", {}).get("profit_taken_ratio", 0)
        if profit_taken >= ALERT_THRESHOLDS["profit_taking_warning"]:
            alerts.append({
                "type": "profit_taking",
                "severity": "warning",
                "title": "Profit Taking Warning",
                "message": f"{profit_taken*100:.0f}% of profits realized",
                "token": symbol,
            })

    # Distribution warning
    if flow_24h < -100000:
        alerts.append({
            "type": "distribution",
            "severity": "warning",
            "title": "Distribution Detected",
            "message": f"${abs(flow_24h):,.0f} outflow in 24h",
            "token": symbol,
        })

    return alerts


# ============== API ENDPOINTS ==============

@app.get("/api/flows")
def api_flows():
    """Get smart money flows - inflows and outflows."""
    chains = request.args.getlist("chain") or DEFAULT_CHAINS

    # Fetch inflows (highest positive flows first)
    inflow_data = fetch_smart_money_netflow(chains, direction="DESC")
    inflow_items = inflow_data.get("data", [])

    # Fetch outflows separately (most negative flows first)
    outflow_data = fetch_smart_money_netflow(chains, direction="ASC")
    outflow_items = outflow_data.get("data", [])

    # Filter by quality thresholds (mcap > $100M, age > 30d)
    inflow_items = [i for i in inflow_items if passes_token_filter(i)]
    outflow_items = [i for i in outflow_items if passes_token_filter(i)]

    def parse_flow(item):
        return {
            "token": item.get("token_symbol", "???"),
            "token_address": item.get("token_address", ""),
            "chain": item.get("chain", ""),
            "flow_1h": item.get("net_flow_1h_usd", 0) or 0,
            "flow_24h": item.get("net_flow_24h_usd", 0) or 0,
            "flow_7d": item.get("net_flow_7d_usd", 0) or 0,
            "flow_30d": item.get("net_flow_30d_usd", 0) or 0,
            "market_cap": item.get("market_cap_usd", 0) or 0,
            "trader_count": item.get("trader_count", 0),
            "token_age_days": item.get("token_age_days", 0),
        }

    # Filter inflows (positive 24h flow)
    inflows = [parse_flow(item) for item in inflow_items if (item.get("net_flow_24h_usd", 0) or 0) > 0]

    # Filter outflows (negative 24h flow)
    outflows = [parse_flow(item) for item in outflow_items if (item.get("net_flow_24h_usd", 0) or 0) < 0]

    return jsonify({
        "inflows": inflows[:25],
        "outflows": outflows[:25],
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/holdings")
def api_holdings():
    """Get smart money top holdings."""
    chains = request.args.getlist("chain") or DEFAULT_CHAINS

    data = fetch_smart_money_holdings(chains)
    holdings_data = data.get("data", [])

    # Filter by market cap (holdings may not have age data)
    holdings_data = [h for h in holdings_data if (h.get("market_cap_usd", 0) or 0) >= MIN_MARKET_CAP]

    holdings = []
    for item in holdings_data:
        holdings.append({
            "token": item.get("token_symbol", "???"),
            "token_address": item.get("token_address", ""),
            "chain": item.get("chain", ""),
            "value_usd": item.get("value_usd", 0) or 0,
            "change_24h": item.get("balance_24h_percent_change", 0) or 0,
            "holders_count": item.get("holders_count", 0),
            "share_percent": item.get("share_of_holdings_percent", 0) or 0,
            "market_cap": item.get("market_cap_usd", 0) or 0,
        })

    return jsonify({
        "holdings": holdings[:30],
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/trades")
def api_trades():
    """Get live DEX trades from smart money."""
    chains = request.args.getlist("chain") or DEFAULT_CHAINS
    min_usd = float(request.args.get("min_usd", 1000))

    data = fetch_smart_money_dex_trades(chains)
    trades_data = data.get("data", [])

    trades = []
    for t in trades_data:
        value_usd = t.get("trade_value_usd", 0) or 0
        if value_usd < min_usd:
            continue

        token_bought = t.get("token_bought_symbol", "") or "???"
        token_sold = t.get("token_sold_symbol", "") or "???"
        trader_label = t.get("trader_address_label", "")
        trader_address = t.get("trader_address", "")

        trades.append({
            "timestamp": t.get("block_timestamp", ""),
            "time_ago": time_ago(t.get("block_timestamp", "")),
            "trader": trader_label or (trader_address[:8] + "..." if trader_address else "Unknown"),
            "trader_address": trader_address,
            "token_bought": token_bought,
            "token_bought_address": t.get("token_bought_address", ""),
            "token_sold": token_sold,
            "token_sold_address": t.get("token_sold_address", ""),
            "amount_bought": t.get("token_bought_amount", 0),
            "amount_sold": t.get("token_sold_amount", 0),
            "value_usd": value_usd,
            "chain": t.get("chain", ""),
        })

    return jsonify({
        "trades": trades[:50],
        "count": len(trades),
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/token/search/<symbol>")
def api_token_search(symbol):
    """Search for token by symbol and return smart money data across chains.

    Uses CoinGecko to resolve symbol to contract addresses, then queries Nansen
    for flow intelligence on each chain.
    """
    # Step 1: Look up token in CoinGecko
    token_info = lookup_token_by_symbol(symbol)
    if not token_info:
        return jsonify({
            "error": f"Token '{symbol}' not found",
            "suggestion": "Try the exact symbol (e.g., ONDO, SYRUP, PEPE)"
        }), 404

    # Step 2: Query Nansen for each chain where token has a contract
    chain_data = []
    for chain, address in token_info.get("addresses", {}).items():
        if not address:
            continue

        # Get flow intelligence from Nansen
        flow_data = fetch_flow_intelligence(address, chain)
        flow = flow_data.get("data", [{}])[0] if flow_data.get("data") else {}

        if flow:
            chain_data.append({
                "chain": chain,
                "address": address,
                "smart_money_flow": {
                    "whale_net_flow": flow.get("whale_net_flow_usd", 0) or 0,
                    "smart_net_flow": flow.get("smart_trader_net_flow_usd", 0) or 0,
                    "exchange_net_flow": flow.get("exchange_net_flow_usd", 0) or 0,
                },
                "holder_counts": {
                    "whale": flow.get("whale_holder_count", 0) or 0,
                    "smart": flow.get("smart_trader_holder_count", 0) or 0,
                    "exchange": flow.get("exchange_holder_count", 0) or 0,
                },
            })
        else:
            # Still include chain even if no flow data
            chain_data.append({
                "chain": chain,
                "address": address,
                "smart_money_flow": None,
                "holder_counts": None,
            })

    # Calculate totals across all chains
    total_whale_flow = sum(c["smart_money_flow"]["whale_net_flow"] for c in chain_data if c.get("smart_money_flow"))
    total_smart_flow = sum(c["smart_money_flow"]["smart_net_flow"] for c in chain_data if c.get("smart_money_flow"))

    return jsonify({
        "symbol": token_info["symbol"],
        "name": token_info["name"],
        "market_cap_usd": token_info.get("market_cap_usd", 0),
        "price_usd": token_info.get("price_usd", 0),
        "price_change_24h": token_info.get("price_change_24h", 0),
        "image": token_info.get("image", ""),
        "chains": chain_data,
        "summary": {
            "total_whale_flow_usd": total_whale_flow,
            "total_smart_flow_usd": total_smart_flow,
            "chains_with_data": len([c for c in chain_data if c.get("smart_money_flow")]),
            "signal": "accumulation" if total_whale_flow + total_smart_flow > 0 else "distribution"
        },
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/token/<chain>/<token_address>")
def api_token_detail(chain, token_address):
    """Get detailed intelligence for a specific token."""
    # Flow intelligence
    flow_data = fetch_flow_intelligence(token_address, chain)
    flow = flow_data.get("data", [{}])[0] if flow_data.get("data") else {}

    # P/L leaderboard - top traders by profit
    pnl_data = fetch_pnl_leaderboard(token_address, chain)
    pnl_leaders = []
    for trader in pnl_data.get("data", [])[:15]:
        pnl_leaders.append({
            "address": trader.get("trader_address", ""),
            "label": trader.get("trader_address_label", ""),
            "pnl_realized": trader.get("pnl_usd_realised", 0) or 0,
            "pnl_unrealized": trader.get("pnl_usd_unrealised", 0) or 0,
            "pnl_total": trader.get("pnl_usd_total", 0) or 0,
            "roi_percent": trader.get("roi_percent_total", 0) or 0,
            "trades": trader.get("nof_trades", 0),
            "holding_usd": trader.get("holding_usd", 0) or 0,
            "max_holding_usd": trader.get("max_balance_held_usd", 0) or 0,
        })

    # Token holders - who holds this token
    holders_data = fetch_token_holders(token_address, chain)
    holders = []
    holder_breakdown = {}  # Count by category

    for holder in holders_data.get("data", [])[:30]:
        label = holder.get("address_label", "")
        category, emoji, category_name = categorize_trader(label)

        # Count for breakdown
        if category not in holder_breakdown:
            holder_breakdown[category] = {"count": 0, "value_usd": 0, "name": category_name, "emoji": emoji}
        holder_breakdown[category]["count"] += 1
        holder_breakdown[category]["value_usd"] += holder.get("value_usd", 0) or 0

        holders.append({
            "address": holder.get("address", ""),
            "label": label,
            "category": category,
            "category_emoji": emoji,
            "category_name": category_name,
            "token_amount": holder.get("token_amount", 0) or 0,
            "value_usd": holder.get("value_usd", 0) or 0,
            "ownership_percent": holder.get("ownership_percentage", 0) or 0,
            "total_inflow": holder.get("total_inflow", 0) or 0,
            "total_outflow": holder.get("total_outflow", 0) or 0,
            "change_24h": holder.get("balance_change_24h", 0) or 0,
            "change_7d": holder.get("balance_change_7d", 0) or 0,
            "change_30d": holder.get("balance_change_30d", 0) or 0,
        })

    # Also categorize P/L leaders
    for leader in pnl_leaders:
        category, emoji, category_name = categorize_trader(leader.get("label", ""))
        leader["category"] = category
        leader["category_emoji"] = emoji
        leader["category_name"] = category_name

    return jsonify({
        "token_address": token_address,
        "chain": chain,
        "flow_intelligence": {
            "whale": {
                "net_flow": flow.get("whale_net_flow_usd", 0) or 0,
                "avg_flow": flow.get("whale_avg_flow_usd", 0) or 0,
                "wallet_count": flow.get("whale_wallet_count", 0),
            },
            "smart_trader": {
                "net_flow": flow.get("smart_trader_net_flow_usd", 0) or 0,
                "avg_flow": flow.get("smart_trader_avg_flow_usd", 0) or 0,
                "wallet_count": flow.get("smart_trader_wallet_count", 0),
            },
            "exchange": {
                "net_flow": flow.get("exchange_net_flow_usd", 0) or 0,
                "avg_flow": flow.get("exchange_avg_flow_usd", 0) or 0,
                "wallet_count": flow.get("exchange_wallet_count", 0),
            },
            "top_pnl": {
                "net_flow": flow.get("top_pnl_net_flow_usd", 0) or 0,
                "avg_flow": flow.get("top_pnl_avg_flow_usd", 0) or 0,
                "wallet_count": flow.get("top_pnl_wallet_count", 0),
            },
        },
        "holder_breakdown": holder_breakdown,
        "holders": holders[:20],
        "pnl_leaderboard": pnl_leaders,
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/trader/<chain>/<address>")
def api_trader_profile(chain, address):
    """Get detailed profile for a specific trader."""
    # P/L summary (30 days and 90 days for comparison)
    pnl_30d = fetch_trader_pnl(address, chain, days=30)
    pnl_90d = fetch_trader_pnl(address, chain, days=90)

    # Transaction history
    txs_data = fetch_trader_transactions(address, chain)
    transactions = []
    for tx in txs_data.get("data", [])[:30]:
        transactions.append({
            "timestamp": tx.get("block_timestamp", ""),
            "time_ago": time_ago(tx.get("block_timestamp", "")),
            "method": tx.get("method", ""),
            "tokens_sent": tx.get("tokens_sent", []),
            "tokens_received": tx.get("tokens_received", []),
            "volume_usd": tx.get("volume_usd", 0) or 0,
            "tx_hash": tx.get("transaction_hash", ""),
        })

    # Top tokens from P/L (use 90d for better picture)
    top_tokens = []
    for token in pnl_90d.get("top5_tokens", []):
        top_tokens.append({
            "symbol": token.get("token_symbol", "???"),
            "address": token.get("token_address", ""),
            "chain": token.get("chain", chain),
            "pnl": token.get("realized_pnl", 0) or 0,
            "roi": token.get("realized_roi", 0) or 0,
        })

    # Calculate trader persona/tier based on performance
    win_rate = pnl_90d.get("win_rate", 0) or 0
    realized_pnl = pnl_90d.get("realized_pnl_usd", 0) or 0
    total_trades = pnl_90d.get("traded_times", 0) or 0

    # Determine performance tier
    if win_rate >= 0.7 and realized_pnl > 100000:
        performance_tier = "elite"
        tier_emoji = "🏆"
        tier_name = "Elite Trader"
    elif win_rate >= 0.6 and realized_pnl > 50000:
        performance_tier = "pro"
        tier_emoji = "⭐"
        tier_name = "Pro Trader"
    elif win_rate >= 0.5 and realized_pnl > 10000:
        performance_tier = "skilled"
        tier_emoji = "📈"
        tier_name = "Skilled Trader"
    elif win_rate >= 0.4:
        performance_tier = "active"
        tier_emoji = "🔄"
        tier_name = "Active Trader"
    else:
        performance_tier = "retail"
        tier_emoji = "👤"
        tier_name = "Retail Trader"

    # Determine trading style based on patterns
    trading_styles = []
    if total_trades > 100:
        trading_styles.append("High Frequency")
    if len(top_tokens) == 1:
        trading_styles.append("Token Specialist")
    elif len(top_tokens) >= 4:
        trading_styles.append("Diversified")
    if realized_pnl > 0 and win_rate >= 0.6:
        trading_styles.append("Consistent Winner")

    return jsonify({
        "address": address,
        "chain": chain,
        "persona": {
            "tier": performance_tier,
            "tier_emoji": tier_emoji,
            "tier_name": tier_name,
            "trading_styles": trading_styles,
        },
        "pnl_summary": {
            "realized_pnl": pnl_30d.get("realized_pnl_usd", 0) or 0,
            "realized_pnl_90d": realized_pnl,
            "realized_pnl_percent": pnl_30d.get("realized_pnl_percent", 0) or 0,
            "win_rate": pnl_30d.get("win_rate", 0) or 0,
            "win_rate_90d": win_rate,
            "traded_tokens": pnl_30d.get("traded_token_count", 0),
            "traded_tokens_90d": pnl_90d.get("traded_token_count", 0),
            "total_trades": pnl_30d.get("traded_times", 0),
            "total_trades_90d": total_trades,
        },
        "top_tokens": top_tokens,
        "transactions": transactions,
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/signals")
def api_signals():
    """Generate actionable trading signals from the data (48h lookback)."""
    # Get flows - sorted by highest inflows
    flows_data = fetch_smart_money_netflow(direction="DESC")
    netflow = flows_data.get("data", [])

    # Filter by quality thresholds (mcap > $100M, age > 30d)
    netflow = [n for n in netflow if passes_token_filter(n)]

    # Get trades
    trades_data = fetch_smart_money_dex_trades()
    trades = trades_data.get("data", [])

    signals = {
        "whale_accumulation": [],
        "smart_divergence": [],
        "new_token_alpha": [],
        "large_trades": [],
    }

    # 1. Whale Accumulation - using 7d flow to capture 48h+ activity
    # Lower thresholds to show more data
    for item in netflow[:100]:
        flow_1h = item.get("net_flow_1h_usd", 0) or 0
        flow_24h = item.get("net_flow_24h_usd", 0) or 0
        flow_7d = item.get("net_flow_7d_usd", 0) or 0

        # Include if any significant positive flow in last 7 days
        # This captures 48h+ of activity
        if flow_24h > 10000 or flow_7d > 25000:
            strength = "STRONG"
            if flow_1h > 25000:
                strength = "STRONG"
            elif flow_24h > 50000:
                strength = "STRONG"
            elif flow_24h > 10000:
                strength = "MODERATE"
            else:
                strength = "BUILDING"

            signals["whale_accumulation"].append({
                "token": item.get("token_symbol", "???"),
                "token_address": item.get("token_address", ""),
                "chain": item.get("chain", ""),
                "flow_1h": flow_1h,
                "flow_24h": flow_24h,
                "flow_7d": flow_7d,
                "market_cap": item.get("market_cap_usd", 0) or 0,
                "strength": strength,
            })

    # 2. New Token Alpha - tokens < 30 days old (expanded from 14)
    for item in netflow[:100]:
        age = item.get("token_age_days", 999)
        flow_24h = item.get("net_flow_24h_usd", 0) or 0
        flow_7d = item.get("net_flow_7d_usd", 0) or 0
        traders = item.get("trader_count", 0)

        # Lower threshold and expanded age window
        if age <= 30 and (flow_24h > 5000 or flow_7d > 10000) and traders >= 2:
            signals["new_token_alpha"].append({
                "token": item.get("token_symbol", "???"),
                "token_address": item.get("token_address", ""),
                "chain": item.get("chain", ""),
                "age_days": age,
                "flow_24h": flow_24h,
                "flow_7d": flow_7d,
                "trader_count": traders,
                "market_cap": item.get("market_cap_usd", 0) or 0,
            })

    # 3. Large Trades - lower threshold to $10K
    for t in trades[:100]:
        value = t.get("trade_value_usd", 0) or 0
        if value >= 10000:
            signals["large_trades"].append({
                "trader": t.get("trader_address_label", ""),
                "trader_address": t.get("trader_address", ""),
                "token_bought": t.get("token_bought_symbol", ""),
                "token_sold": t.get("token_sold_symbol", ""),
                "value_usd": value,
                "chain": t.get("chain", ""),
                "time_ago": time_ago(t.get("block_timestamp", "")),
            })

    # Sort by strength/value
    signals["whale_accumulation"].sort(key=lambda x: x["flow_24h"], reverse=True)
    signals["new_token_alpha"].sort(key=lambda x: x["flow_24h"], reverse=True)
    signals["large_trades"].sort(key=lambda x: x["value_usd"], reverse=True)

    return jsonify({
        "signals": {
            "whale_accumulation": signals["whale_accumulation"][:15],
            "new_token_alpha": signals["new_token_alpha"][:15],
            "large_trades": signals["large_trades"][:20],
        },
        "summary": {
            "whale_accumulation": len(signals["whale_accumulation"]),
            "new_token_alpha": len(signals["new_token_alpha"]),
            "large_trades": len(signals["large_trades"]),
        },
        "generated_at": datetime.now().isoformat(),
    })


# ============== DEEP INTELLIGENCE ENDPOINTS ==============

@app.get("/api/snapshot/save")
def api_save_snapshot():
    """Manually trigger a snapshot save (normally run via cron)."""
    result = save_daily_snapshot()
    return jsonify(result)


@app.get("/api/token/<chain>/<token_address>/intelligence")
def api_token_intelligence(chain, token_address):
    """Get comprehensive intelligence for a token including accumulation score,
    entry quality, conviction analysis, and alerts.
    """
    # Get basic flow data first
    flow_data = fetch_flow_intelligence(token_address, chain)
    flow = flow_data.get("data", [{}])[0] if flow_data.get("data") else {}

    # Get P/L leaderboard for entry quality
    pnl_data = fetch_pnl_leaderboard(token_address, chain)
    pnl_leaders = pnl_data.get("data", [])

    # Get holders for conviction analysis
    holders_data = fetch_token_holders(token_address, chain)
    holders = holders_data.get("data", [])

    # Build token data dict for calculations
    token_data = {
        "token_address": token_address,
        "chain": chain,
        "token_symbol": "TOKEN",  # Will be populated from flow data
        "net_flow_24h_usd": flow.get("total_net_flow_usd", 0) or 0,
        "net_flow_7d_usd": (flow.get("total_net_flow_usd", 0) or 0) * 3,  # Estimate
        "net_flow_30d_usd": (flow.get("total_net_flow_usd", 0) or 0) * 10,  # Estimate
        "trader_count": (flow.get("whale_wallet_count", 0) or 0) +
                       (flow.get("smart_trader_wallet_count", 0) or 0),
        "price_change_24h": 0,  # Would need price API
    }

    # Calculate all intelligence metrics
    accumulation_score = calculate_accumulation_score(token_data)
    entry_quality = analyze_entry_quality(pnl_leaders)
    conviction = analyze_holder_conviction(holders)
    related = find_related_tokens(token_address, chain, holders_data)
    alerts = check_alerts(token_data, accumulation_score, entry_quality)

    # Get historical data if available
    history = get_historical_flows(token_address, days=14)

    return jsonify({
        "token_address": token_address,
        "chain": chain,
        "accumulation_score": accumulation_score,
        "entry_quality": entry_quality,
        "conviction_analysis": conviction,
        "related_tokens": related,
        "alerts": alerts,
        "flow_summary": {
            "whale_flow": flow.get("whale_net_flow_usd", 0) or 0,
            "smart_flow": flow.get("smart_trader_net_flow_usd", 0) or 0,
            "exchange_flow": flow.get("exchange_net_flow_usd", 0) or 0,
        },
        "historical_flows": history,
        "pnl_leader_count": len(pnl_leaders),
        "holder_count": len(holders),
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/alerts")
def api_alerts():
    """Get alerts for all tracked tokens based on current conditions."""
    # Get top flows
    flows_data = fetch_smart_money_netflow(direction="DESC")
    flows = flows_data.get("data", [])

    # Filter and collect alerts
    all_alerts = []
    for token_data in flows[:50]:  # Check top 50 tokens
        if not passes_token_filter(token_data):
            continue

        # Calculate accumulation score
        acc_score = calculate_accumulation_score(token_data)

        # Check for alerts
        alerts = check_alerts(token_data, acc_score)
        for alert in alerts:
            alert["token_address"] = token_data.get("token_address", "")
            alert["chain"] = token_data.get("chain", "")
            all_alerts.append(alert)

    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "warning": 2, "low": 3}
    all_alerts.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 99))

    return jsonify({
        "alerts": all_alerts[:30],
        "total_alerts": len(all_alerts),
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/leaderboard")
def api_accumulation_leaderboard():
    """Get tokens ranked by accumulation score."""
    flows_data = fetch_smart_money_netflow(direction="DESC")
    flows = flows_data.get("data", [])

    scored_tokens = []
    for token_data in flows[:100]:
        if not passes_token_filter(token_data):
            continue

        score = calculate_accumulation_score(token_data)
        scored_tokens.append({
            "token": token_data.get("token_symbol", "???"),
            "token_address": token_data.get("token_address", ""),
            "chain": token_data.get("chain", ""),
            "accumulation_score": score["score"],
            "phase": score["phase"],
            "phase_label": score["phase_label"],
            "flow_24h": token_data.get("net_flow_24h_usd", 0) or 0,
            "flow_7d": token_data.get("net_flow_7d_usd", 0) or 0,
            "trader_count": token_data.get("trader_count", 0),
            "market_cap": token_data.get("market_cap_usd", 0) or 0,
        })

    # Sort by accumulation score
    scored_tokens.sort(key=lambda x: x["accumulation_score"], reverse=True)

    return jsonify({
        "leaderboard": scored_tokens[:25],
        "total_analyzed": len(scored_tokens),
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/watchlist/intelligence")
def api_watchlist_intelligence():
    """Get deep intelligence for watchlist tokens (called from frontend with token list)."""
    # Get tokens from query string (comma-separated addresses)
    tokens_param = request.args.get("tokens", "")
    if not tokens_param:
        return jsonify({"error": "No tokens provided", "tokens": []}), 400

    token_specs = tokens_param.split(",")
    results = []

    for spec in token_specs[:10]:  # Limit to 10 tokens
        parts = spec.split(":")
        if len(parts) != 2:
            continue

        chain, address = parts

        # Get flow intelligence
        flow_data = fetch_flow_intelligence(address, chain)
        flow = flow_data.get("data", [{}])[0] if flow_data.get("data") else {}

        # Build token data
        token_data = {
            "token_address": address,
            "chain": chain,
            "net_flow_24h_usd": flow.get("total_net_flow_usd", 0) or 0,
            "net_flow_7d_usd": (flow.get("total_net_flow_usd", 0) or 0) * 3,
            "trader_count": (flow.get("whale_wallet_count", 0) or 0) +
                           (flow.get("smart_trader_wallet_count", 0) or 0),
        }

        # Calculate score
        acc_score = calculate_accumulation_score(token_data)
        alerts = check_alerts(token_data, acc_score)

        results.append({
            "chain": chain,
            "address": address,
            "accumulation_score": acc_score,
            "alerts": alerts,
            "flow": {
                "whale": flow.get("whale_net_flow_usd", 0) or 0,
                "smart": flow.get("smart_trader_net_flow_usd", 0) or 0,
            },
        })

    return jsonify({
        "tokens": results,
        "generated_at": datetime.now().isoformat(),
    })


# ============== PAGE ROUTES ==============

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/token/<chain>/<token_address>")
def token_page(chain, token_address):
    return render_template("token.html", chain=chain, token_address=token_address)

@app.route("/trader/<chain>/<address>")
def trader_page(chain, address):
    return render_template("trader.html", chain=chain, address=address)

@app.route("/signals")
def signals_page():
    return render_template("signals.html")


# ============== RUN ==============

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
