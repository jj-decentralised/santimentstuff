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


@app.get("/api/token/<chain>/<token_address>")
def api_token_detail(chain, token_address):
    """Get detailed intelligence for a specific token."""
    # Flow intelligence
    flow_data = fetch_flow_intelligence(token_address, chain)
    flow = flow_data.get("data", [{}])[0] if flow_data.get("data") else {}

    # P/L leaderboard
    pnl_data = fetch_pnl_leaderboard(token_address, chain)
    pnl_leaders = []
    for trader in pnl_data.get("data", [])[:10]:
        pnl_leaders.append({
            "address": trader.get("trader_address", ""),
            "label": trader.get("trader_address_label", ""),
            "pnl_realized": trader.get("pnl_usd_realised", 0) or 0,
            "pnl_unrealized": trader.get("pnl_usd_unrealised", 0) or 0,
            "pnl_total": trader.get("pnl_usd_total", 0) or 0,
            "roi_percent": trader.get("roi_percent_total", 0) or 0,
            "trades": trader.get("nof_trades", 0),
            "holding_usd": trader.get("holding_usd", 0) or 0,
        })

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
        "pnl_leaderboard": pnl_leaders,
        "generated_at": datetime.now().isoformat(),
    })


@app.get("/api/trader/<chain>/<address>")
def api_trader_profile(chain, address):
    """Get detailed profile for a specific trader."""
    # P/L summary
    pnl = fetch_trader_pnl(address, chain)

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

    # Top tokens from P/L
    top_tokens = []
    for token in pnl.get("top5_tokens", []):
        top_tokens.append({
            "symbol": token.get("token_symbol", "???"),
            "address": token.get("token_address", ""),
            "chain": token.get("chain", ""),
            "pnl": token.get("realized_pnl", 0) or 0,
            "roi": token.get("realized_roi", 0) or 0,
        })

    return jsonify({
        "address": address,
        "chain": chain,
        "pnl_summary": {
            "realized_pnl": pnl.get("realized_pnl_usd", 0) or 0,
            "realized_pnl_percent": pnl.get("realized_pnl_percent", 0) or 0,
            "win_rate": pnl.get("win_rate", 0) or 0,
            "traded_tokens": pnl.get("traded_token_count", 0),
            "total_trades": pnl.get("traded_times", 0),
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
