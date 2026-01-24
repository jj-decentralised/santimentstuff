"""Fund Activity Tracker - What are funds doing today?"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

# Config
BASE_URL = "https://api.arkm.com"
BASE_DIR = Path(__file__).parent
CACHE_REFRESH_SECONDS = 300  # 5 minutes

# Verified fund entities from Arkham Intelligence (type: "fund")
# These IDs are verified to exist and be classified as funds in Arkham's database
ENTITIES = {
    # Major VCs & Crypto Funds
    "jump-trading": "Jump Crypto",
    "wintermute": "Wintermute",
    "a16z": "a16z",
    "paradigm-capital": "Paradigm",
    "pantera-capital": "Pantera Capital",
    "polychain-capital": "Polychain Capital",
    "dragonfly-capital": "Dragonfly Capital",
    "blockchain-capital": "Blockchain Capital",
    "electric-capital": "Electric Capital",
    "variant-fund": "Variant Fund",
    "nascent": "Nascent",
    "mechanism-capital": "Mechanism Capital",
    "placeholder-vc": "Placeholder VC",
    "hack-vc": "Hack VC",
    "banklessvc": "Bankless VC",
    # Asset Managers & Institutional
    "grayscale": "Grayscale",
    "galaxy-digital": "Galaxy Digital",
    "digital-currency-group": "DCG",
    "sequoia-capital": "Sequoia Capital",
    "animoca-brands": "Animoca Brands",
    "fabric-ventures": "Fabric Ventures",
    "delphi-digital": "Delphi Digital",
    "maven-11": "Maven 11",
    "mirana-ventures": "Mirana Ventures",
    # Market Makers (type: fund)
    "cumberland": "Cumberland DRW",
    "dwf-labs": "DWF Labs",
    "tokka-labs": "Tokka Labs",
    "akuna-capital": "Akuna Capital",
    "winklevoss-capital": "Winklevoss Capital",
    # Additional VCs
    "1confirmation": "1confirmation",
    "spartan-group": "Spartan Group",
    "framework-ventures": "Framework Ventures",
    "binance-labs": "YZi Labs (Binance Labs)",
    # Market Makers (additional)
    "gsr-markets": "GSR Markets",
    "amber": "Amber Group",
    "b2c2": "B2C2 Group",
    "jane-street": "Jane Street",
    # Institutional ETF
    "blackrock": "BlackRock",
    "fidelity": "Fidelity FBTC ETF",
    "fidelity-ethereum-etf": "Fidelity FETH ETF",
    # Other Funds
    "three-arrows-capital": "3AC",
    "cms-holdings": "CMS Holdings",
    "big-brain-holdings": "Big Brain Holdings",
    "abraxas-capital-heka-funds": "Abraxas Capital",
    "sigil-fund": "Sigil Fund",
    "pharos": "Pharos Fund",
    "polder-fund": "Polder Fund",
    "apollo-capital": "Apollo Crypto",
    "astelek-crypto-fund": "Astelek Crypto Fund",
    "scp": "Symbolic Capital Partners",
    "simply-vc": "Simply VC",
    "ngc-ventures": "NGC Ventures",
    "ci-global-asset-management": "CI Global Asset Mgmt",
    "silveridge-holdings": "Silveridge Holdings",
}

# In-memory cache
cache = {
    "activity": None,
    "last_updated": None,
    "is_refreshing": False,
}
cache_lock = threading.Lock()

app = FastAPI(title="Fund Activity Tracker")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_api_key():
    return os.environ.get("ARKHAM_API_KEY", "")


def fetch_fund_transfers(fund_id: str, limit: int = 50, min_usd: int = 10000) -> list:
    """Fetch recent transfers for a fund with minimum USD filter."""
    try:
        r = httpx.get(
            f"{BASE_URL}/transfers",
            params={
                "base": fund_id,
                "limit": limit,
                "sortDir": "desc",
                "usdGte": min_usd,
            },
            headers={"API-Key": get_api_key()},
            timeout=15,  # Reduced timeout
        )
        r.raise_for_status()
        return r.json().get("transfers", [])
    except httpx.TimeoutException:
        print(f"Timeout fetching {fund_id}")
        return []
    except Exception as e:
        print(f"Error fetching {fund_id}: {e}")
        return []


# Known exchanges for flow analysis
EXCHANGES = {
    "binance", "coinbase", "kraken", "okx", "bybit", "bitfinex", "kucoin",
    "huobi", "gate-io", "gemini", "bitstamp", "ftx", "crypto-com", "mexc",
}

# Token categories for grouping
TOKEN_CATEGORIES = {
    # Stablecoins
    "USDT": "stable", "USDC": "stable", "DAI": "stable", "USDE": "stable",
    "FRAX": "stable", "TUSD": "stable", "BUSD": "stable", "USDP": "stable",
    # Major L1s
    "ETH": "l1", "WETH": "l1", "BTC": "l1", "WBTC": "l1", "BTCB": "l1",
    "SOL": "l1", "AVAX": "l1", "BNB": "l1", "ADA": "l1", "DOT": "l1",
    # L2s
    "ARB": "l2", "OP": "l2", "MATIC": "l2", "BASE": "l2", "STRK": "l2",
    # DeFi
    "UNI": "defi", "AAVE": "defi", "MKR": "defi", "LDO": "defi", "CRV": "defi",
    "COMP": "defi", "SNX": "defi", "SUSHI": "defi", "YFI": "defi", "PENDLE": "defi",
    "ENA": "defi", "EIGEN": "defi", "MORPHO": "defi",
    # Meme
    "DOGE": "meme", "SHIB": "meme", "PEPE": "meme", "FLOKI": "meme",
    "BONK": "meme", "WIF": "meme", "TRUMP": "meme", "MEME": "meme",
    # AI
    "FET": "ai", "AGIX": "ai", "RNDR": "ai", "TAO": "ai", "NEAR": "ai",
}


def parse_transfer(tx: dict, fund_id: str, fund_name: str) -> dict | None:
    """Parse a transfer into a clean activity item."""
    usd = tx.get("historicalUSD", 0) or 0
    if usd < 1000:
        return None

    to_entity = (tx.get("toAddress") or {}).get("arkhamEntity") or {}
    from_entity = (tx.get("fromAddress") or {}).get("arkhamEntity") or {}

    if to_entity.get("id") == fund_id:
        action = "Received"
        counterparty = from_entity.get("name") or "Unknown"
        counterparty_id = from_entity.get("id") or ""
        counterparty_type = from_entity.get("type") or ""
    elif from_entity.get("id") == fund_id:
        action = "Sent"
        counterparty = to_entity.get("name") or "Unknown"
        counterparty_id = to_entity.get("id") or ""
        counterparty_type = to_entity.get("type") or ""
    else:
        return None

    # Detect exchange involvement
    is_exchange = counterparty_type == "cex" or counterparty_id in EXCHANGES

    ts = tx.get("blockTimestamp", "")
    hours_ago = 0
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        time_ago = datetime.now(dt.tzinfo) - dt
        hours_ago = time_ago.total_seconds() / 3600
        if time_ago.days > 0:
            time_str = f"{time_ago.days}d ago"
        elif time_ago.seconds > 3600:
            time_str = f"{time_ago.seconds // 3600}h ago"
        else:
            time_str = f"{time_ago.seconds // 60}m ago"
    except:
        time_str = "?"

    token = (tx.get("tokenSymbol") or "???").upper()

    return {
        "timestamp": ts,
        "time_ago": time_str,
        "hours_ago": hours_ago,
        "fund_id": fund_id,
        "fund": fund_name,
        "action": action,
        "token": token,
        "token_name": tx.get("tokenName") or "",
        "category": TOKEN_CATEGORIES.get(token, "other"),
        "amount": tx.get("unitValue", 0) or 0,
        "usd": usd,
        "counterparty": counterparty[:25],
        "counterparty_type": counterparty_type,
        "is_exchange": is_exchange,
        "chain": tx.get("chain", ""),
        "tx_hash": tx.get("transactionHash", ""),
    }


def fetch_entity_activity(entity_id: str, entity_name: str, min_usd: int, limit: int) -> list:
    """Fetch and parse transfers for a single entity."""
    results = []
    try:
        transfers = fetch_fund_transfers(entity_id, limit=limit, min_usd=min_usd)
        for tx in transfers:
            item = parse_transfer(tx, entity_id, entity_name)
            if item:
                results.append(item)
    except Exception as e:
        print(f"Error processing {entity_id}: {e}")
    return results


def build_activity_data(min_usd: int = 10000, limit_per_entity: int = 30) -> dict:
    """Build full activity data from all entities using concurrent requests."""
    all_activity = []

    # Fetch all entities concurrently (10 at a time)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_entity_activity, eid, ename, min_usd, limit_per_entity): eid
            for eid, ename in ENTITIES.items()
        }
        for future in as_completed(futures):
            entity_id = futures[future]
            try:
                results = future.result()
                all_activity.extend(results)
                print(f"  Fetched {len(results)} txs from {entity_id}")
            except Exception as e:
                print(f"  Failed {entity_id}: {e}")

    all_activity.sort(key=lambda x: x["timestamp"], reverse=True)

    total_received = sum(a["usd"] for a in all_activity if a["action"] == "Received")
    total_sent = sum(a["usd"] for a in all_activity if a["action"] == "Sent")

    # Token flows with fund tracking and categories
    token_data = {}
    for a in all_activity:
        token = a["token"]
        if token not in token_data:
            token_data[token] = {
                "received": 0, "sent": 0,
                "buyers": set(), "sellers": set(),
                "category": a.get("category", "other"),
            }
        if a["action"] == "Received":
            token_data[token]["received"] += a["usd"]
            token_data[token]["buyers"].add(a["fund"])
        else:
            token_data[token]["sent"] += a["usd"]
            token_data[token]["sellers"].add(a["fund"])

    # Top tokens by flow
    top_tokens = sorted(
        [
            {
                "token": t, "net": d["received"] - d["sent"],
                "received": d["received"], "sent": d["sent"],
                "category": d["category"],
            }
            for t, d in token_data.items()
        ],
        key=lambda x: abs(x["net"]),
        reverse=True,
    )[:10]

    # Smart Money Consensus - tokens with multiple funds buying/selling
    consensus = []
    for token, data in token_data.items():
        net = data["received"] - data["sent"]
        buyer_count = len(data["buyers"])
        seller_count = len(data["sellers"])
        if (buyer_count >= 2 or seller_count >= 2) and (data["received"] + data["sent"]) > 50000:
            consensus.append({
                "token": token,
                "category": data["category"],
                "net": net,
                "received": data["received"],
                "sent": data["sent"],
                "buyer_count": buyer_count,
                "seller_count": seller_count,
                "buyers": list(data["buyers"])[:5],
                "sellers": list(data["sellers"])[:5],
                "signal": "BULLISH" if net > 0 and buyer_count > seller_count else "BEARISH" if net < 0 and seller_count > buyer_count else "MIXED",
            })
    consensus.sort(key=lambda x: x["buyer_count"] + x["seller_count"], reverse=True)

    # === EXCHANGE FLOW ANALYSIS ===
    exchange_flows = {"to_exchange": 0, "from_exchange": 0, "to_exchange_txs": [], "from_exchange_txs": []}
    for a in all_activity:
        if a.get("is_exchange"):
            if a["action"] == "Sent":  # Fund sending TO exchange = likely selling
                exchange_flows["to_exchange"] += a["usd"]
                if len(exchange_flows["to_exchange_txs"]) < 10:
                    exchange_flows["to_exchange_txs"].append(a)
            else:  # Fund receiving FROM exchange = likely buying
                exchange_flows["from_exchange"] += a["usd"]
                if len(exchange_flows["from_exchange_txs"]) < 10:
                    exchange_flows["from_exchange_txs"].append(a)
    exchange_flows["net"] = exchange_flows["from_exchange"] - exchange_flows["to_exchange"]
    exchange_flows["signal"] = "BULLISH" if exchange_flows["net"] > 0 else "BEARISH" if exchange_flows["net"] < 0 else "NEUTRAL"

    # === CATEGORY BREAKDOWN ===
    category_flows = {}
    for a in all_activity:
        cat = a.get("category", "other")
        if cat not in category_flows:
            category_flows[cat] = {"received": 0, "sent": 0}
        if a["action"] == "Received":
            category_flows[cat]["received"] += a["usd"]
        else:
            category_flows[cat]["sent"] += a["usd"]

    categories = sorted(
        [
            {
                "category": cat,
                "received": d["received"],
                "sent": d["sent"],
                "net": d["received"] - d["sent"],
                "volume": d["received"] + d["sent"],
            }
            for cat, d in category_flows.items()
        ],
        key=lambda x: x["volume"],
        reverse=True,
    )

    # === RECENT ACTIVITY (Last 4 hours) ===
    recent_4h = [a for a in all_activity if a.get("hours_ago", 999) <= 4]
    recent_received = sum(a["usd"] for a in recent_4h if a["action"] == "Received")
    recent_sent = sum(a["usd"] for a in recent_4h if a["action"] == "Sent")

    # === FUND LEADERBOARD ===
    fund_stats = {}
    fund_tokens = {}  # Track tokens per fund for "new position" detection
    for a in all_activity:
        fid = a["fund_id"]
        if fid not in fund_stats:
            fund_stats[fid] = {"name": a["fund"], "received": 0, "sent": 0, "tx_count": 0, "exchange_sells": 0}
            fund_tokens[fid] = set()
        fund_stats[fid]["tx_count"] += 1
        fund_tokens[fid].add(a["token"])
        if a["action"] == "Received":
            fund_stats[fid]["received"] += a["usd"]
        else:
            fund_stats[fid]["sent"] += a["usd"]
            if a.get("is_exchange"):
                fund_stats[fid]["exchange_sells"] += a["usd"]

    fund_leaderboard = sorted(
        [
            {
                "fund_id": fid,
                "name": d["name"],
                "received": d["received"],
                "sent": d["sent"],
                "net": d["received"] - d["sent"],
                "volume": d["received"] + d["sent"],
                "tx_count": d["tx_count"],
                "exchange_sells": d["exchange_sells"],
                "token_count": len(fund_tokens.get(fid, [])),
            }
            for fid, d in fund_stats.items()
        ],
        key=lambda x: x["volume"],
        reverse=True,
    )[:15]

    # === WHALE ALERTS ===
    whale_threshold = 500000
    whales = [a for a in all_activity if a["usd"] >= whale_threshold][:20]

    # === NEW/UNUSUAL TOKENS (tokens with only 1-2 funds touching them recently) ===
    # These could be early signals
    emerging_tokens = []
    for token, data in token_data.items():
        total_funds = len(data["buyers"] | data["sellers"])
        if 1 <= total_funds <= 3 and (data["received"] + data["sent"]) > 50000:
            # Skip stablecoins
            if data["category"] != "stable":
                emerging_tokens.append({
                    "token": token,
                    "category": data["category"],
                    "funds": list(data["buyers"] | data["sellers"]),
                    "net": data["received"] - data["sent"],
                    "volume": data["received"] + data["sent"],
                    "action": "accumulating" if data["received"] > data["sent"] else "distributing",
                })
    emerging_tokens.sort(key=lambda x: x["volume"], reverse=True)

    return {
        "activity": all_activity[:200],
        "stats": {
            "total_received": total_received,
            "total_sent": total_sent,
            "net_flow": total_received - total_sent,
            "transaction_count": len(all_activity),
            "active_funds": len(fund_stats),
            "tokens_moved": len(token_data),
            # Recent activity (4h)
            "recent_received": recent_received,
            "recent_sent": recent_sent,
            "recent_net": recent_received - recent_sent,
            "recent_count": len(recent_4h),
        },
        "top_tokens": top_tokens,
        "consensus": consensus[:10],
        "fund_leaderboard": fund_leaderboard,
        "whales": whales,
        # New analytics
        "exchange_flows": exchange_flows,
        "categories": categories,
        "emerging_tokens": emerging_tokens[:8],
    }


def refresh_cache():
    """Refresh the activity cache."""
    global cache
    with cache_lock:
        if cache["is_refreshing"]:
            return
        cache["is_refreshing"] = True

    try:
        print(f"[{datetime.now()}] Refreshing activity cache...")
        data = build_activity_data()
        with cache_lock:
            cache["activity"] = data
            cache["last_updated"] = datetime.now()
        print(f"[{datetime.now()}] Cache refreshed with {len(data['activity'])} transactions")
    except Exception as e:
        print(f"[{datetime.now()}] Cache refresh error: {e}")
    finally:
        with cache_lock:
            cache["is_refreshing"] = False


def background_refresh_loop():
    """Background thread that refreshes cache every 5 minutes."""
    while True:
        refresh_cache()
        time.sleep(CACHE_REFRESH_SECONDS)


@app.on_event("startup")
def startup_event():
    """Start background cache refresh on app startup."""
    # Start background thread
    thread = threading.Thread(target=background_refresh_loop, daemon=True)
    thread.start()
    print(f"Started background cache refresh (every {CACHE_REFRESH_SECONDS}s)")


@app.get("/api/activity")
def get_activity(
    min_usd: int = Query(10000, description="Minimum USD value"),
    limit_per_entity: int = Query(30, description="Max transfers per entity"),
):
    """Get recent activity across all entities (from cache)."""
    with cache_lock:
        if cache["activity"] is not None:
            data = cache["activity"].copy()
            data["cached"] = True
            data["cache_age_seconds"] = (
                (datetime.now() - cache["last_updated"]).total_seconds()
                if cache["last_updated"]
                else None
            )
            return data
        is_refreshing = cache["is_refreshing"]

    # No cache yet - return loading state instead of blocking
    return {
        "activity": [],
        "stats": {
            "total_received": 0,
            "total_sent": 0,
            "net_flow": 0,
            "transaction_count": 0,
        },
        "top_tokens": [],
        "loading": True,
        "message": "Cache is building, please refresh in ~60 seconds..." if is_refreshing else "Starting cache build...",
    }


@app.get("/api/activity/refresh")
def force_refresh():
    """Force a cache refresh."""
    thread = threading.Thread(target=refresh_cache, daemon=True)
    thread.start()
    return {"status": "refresh_started"}


@app.get("/api/token/{token_symbol}")
def get_token_activity(token_symbol: str):
    """Get accumulation/distribution for a specific token across all entities."""
    token_symbol = token_symbol.upper()
    entity_activity = {}

    for entity_id, entity_name in ENTITIES.items():
        transfers = fetch_fund_transfers(entity_id, limit=100, min_usd=1000)

        for tx in transfers:
            tx_token = (tx.get("tokenSymbol") or "").upper()
            if tx_token != token_symbol:
                continue

            usd = tx.get("historicalUSD", 0) or 0
            ts = tx.get("blockTimestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                days_ago = (datetime.now(dt.tzinfo) - dt).days
            except:
                continue

            to_entity = (tx.get("toAddress") or {}).get("arkhamEntity") or {}
            from_entity = (tx.get("fromAddress") or {}).get("arkhamEntity") or {}

            if to_entity.get("id") == entity_id:
                direction = "received"
            elif from_entity.get("id") == entity_id:
                direction = "sent"
            else:
                continue

            if entity_id not in entity_activity:
                entity_activity[entity_id] = {
                    "name": entity_name,
                    "7d": {"received": 0, "sent": 0},
                    "30d": {"received": 0, "sent": 0},
                    "90d": {"received": 0, "sent": 0},
                }

            if days_ago <= 7:
                entity_activity[entity_id]["7d"][direction] += usd
            if days_ago <= 30:
                entity_activity[entity_id]["30d"][direction] += usd
            if days_ago <= 90:
                entity_activity[entity_id]["90d"][direction] += usd

    results = []
    for entity_id, data in entity_activity.items():
        net_7d = data["7d"]["received"] - data["7d"]["sent"]
        net_30d = data["30d"]["received"] - data["30d"]["sent"]
        net_90d = data["90d"]["received"] - data["90d"]["sent"]

        if abs(net_30d) > 1000 or abs(net_90d) > 1000:
            results.append({
                "entity_id": entity_id,
                "name": data["name"],
                "net_7d": net_7d,
                "net_30d": net_30d,
                "net_90d": net_90d,
                "received_7d": data["7d"]["received"],
                "sent_7d": data["7d"]["sent"],
                "received_30d": data["30d"]["received"],
                "sent_30d": data["30d"]["sent"],
                "received_90d": data["90d"]["received"],
                "sent_90d": data["90d"]["sent"],
            })

    results.sort(key=lambda x: x["net_30d"], reverse=True)
    accumulators = [r for r in results if r["net_30d"] > 0]
    sellers = [r for r in results if r["net_30d"] < 0]

    return {
        "token": token_symbol,
        "accumulators": accumulators,
        "sellers": sellers,
        "summary": {
            "total_accumulated_30d": sum(r["net_30d"] for r in accumulators),
            "total_sold_30d": abs(sum(r["net_30d"] for r in sellers)),
            "accumulator_count": len(accumulators),
            "seller_count": len(sellers),
        }
    }


@app.get("/health")
def health():
    key = get_api_key()
    with cache_lock:
        cache_status = {
            "has_cache": cache["activity"] is not None,
            "last_updated": cache["last_updated"].isoformat() if cache["last_updated"] else None,
            "is_refreshing": cache["is_refreshing"],
        }
    return {
        "status": "ok",
        "api_key_set": bool(key),
        "entities_tracked": len(ENTITIES),
        "cache": cache_status,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the dashboard."""
    html_path = BASE_DIR / "templates" / "dashboard.html"
    return html_path.read_text()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
