"""
Smart Money Intelligence - Nansen-Powered Dashboard
A comprehensive trading signals platform powered by Nansen's smart money data.
"""

import os
import httpx
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

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
