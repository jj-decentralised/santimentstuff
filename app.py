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
# EXCLUDES market makers - we only want real investment signals
ENTITIES = {
    # Major VCs & Crypto Funds
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
    "1confirmation": "1confirmation",
    "spartan-group": "Spartan Group",
    "framework-ventures": "Framework Ventures",
    "binance-labs": "YZi Labs (Binance Labs)",
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
    "winklevoss-capital": "Winklevoss Capital",
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

# Notable traders - high balance individuals (>$10M AUM)
# Excludes exchanges and market makers
NOTABLE_TRADERS = {
    # Known whale/trader addresses from Arkham
    "0xd8da6bf26964af9d7eed9e03e53415d37aa96045": "vitalik.eth",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Justin Sun",
    "james-fickel": "James Fickel",
    "tetranode": "Tetranode",
    "cobie": "Cobie",
    "hsaka": "Hsaka",
    "lookonchain": "Lookonchain Whale 1",
    "0x1b7baa734c00298b9429b518d621753bb0f6eff2": "Whale (1B7B)",
    "0x8652f3d3db0b79fca9e1d3e5bcffcdbd21b79a6c": "Whale (8652)",
    "0x176f3dab24a159341c0509bb36b833e7fdd0a132": "Whale (176F)",
    "0x3ddfa8ec3052539b6c9549f12cea2c295cff5296": "Smart Money 1",
    "0x66b870ddf78c975af5cd8edc6de25eca81791de1": "Smart Money 2",
    "pranksy": "Pranksy",
    "giancarlo-devasini": "Giancarlo (Tether)",
    "arthur-hayes": "Arthur Hayes",
    "su-zhu": "Su Zhu (3AC)",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x Exchange Proxy",
}

# Entity types we want to track (exclude these from results)
EXCLUDED_TYPES = {"cex", "dex", "bridge", "protocol"}

# Known market makers to exclude from "smart money" signals
MARKET_MAKERS = {
    "wintermute", "jump-trading", "gsr-markets", "cumberland", "b2c2",
    "jane-street", "amber", "dwf-labs", "tokka-labs", "akuna-capital",
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
    """Get comprehensive activity for a specific token across all tracked entities."""
    token_symbol = token_symbol.upper()
    entity_activity = {}

    # All entities to check (funds + notable traders)
    all_entities = {**ENTITIES, **NOTABLE_TRADERS}

    def check_entity(entity_id: str, entity_name: str):
        """Fetch transfers for an entity and filter for the target token."""
        transfers = fetch_fund_transfers(entity_id, limit=100, min_usd=1000)
        results = []
        for tx in transfers:
            tx_token = (tx.get("tokenSymbol") or "").upper()
            if tx_token != token_symbol:
                continue
            results.append(tx)
        return entity_id, results

    # Concurrent fetch for all tracked entities
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(check_entity, eid, ename): eid for eid, ename in all_entities.items()}
        for future in as_completed(futures):
            entity_id = futures[future]
            try:
                eid, transfers = future.result()
                if not transfers:
                    continue

                entity_name = all_entities.get(eid, eid)
                is_fund = eid in ENTITIES
                is_mm = eid in MARKET_MAKERS

                for tx in transfers:
                    usd = tx.get("historicalUSD", 0) or 0
                    if usd < 1000:
                        continue

                    ts = tx.get("blockTimestamp", "")
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        days_ago = (datetime.now(dt.tzinfo) - dt).days
                        time_ago = f"{days_ago}d ago" if days_ago > 0 else "today"
                    except:
                        days_ago = 999
                        time_ago = "?"

                    to_entity = (tx.get("toAddress") or {}).get("arkhamEntity") or {}
                    from_entity = (tx.get("fromAddress") or {}).get("arkhamEntity") or {}

                    if to_entity.get("id") == eid:
                        direction = "received"
                        counterparty = from_entity.get("name") or "Unknown"
                        counterparty_type = from_entity.get("type") or ""
                    elif from_entity.get("id") == eid:
                        direction = "sent"
                        counterparty = to_entity.get("name") or "Unknown"
                        counterparty_type = to_entity.get("type") or ""
                    else:
                        continue

                    if eid not in entity_activity:
                        entity_activity[eid] = {
                            "name": entity_name,
                            "type": "fund" if is_fund else "individual",
                            "is_tracked": True,
                            "is_market_maker": is_mm,
                            "7d": {"received": 0, "sent": 0, "txs": []},
                            "30d": {"received": 0, "sent": 0, "txs": []},
                            "90d": {"received": 0, "sent": 0, "txs": []},
                            "all_txs": [],
                        }

                    tx_record = {
                        "timestamp": ts,
                        "time_ago": time_ago,
                        "days_ago": days_ago,
                        "direction": direction,
                        "usd": usd,
                        "amount": tx.get("unitValue", 0) or 0,
                        "chain": tx.get("chain", ""),
                        "tx_hash": tx.get("transactionHash", ""),
                        "counterparty": counterparty,
                        "counterparty_type": counterparty_type,
                    }

                    # Avoid duplicates
                    existing_hashes = {t["tx_hash"] for t in entity_activity[eid]["all_txs"]}
                    if tx_record["tx_hash"] in existing_hashes:
                        continue

                    entity_activity[eid]["all_txs"].append(tx_record)

                    if days_ago <= 7:
                        entity_activity[eid]["7d"][direction] += usd
                        entity_activity[eid]["7d"]["txs"].append(tx_record)
                    if days_ago <= 30:
                        entity_activity[eid]["30d"][direction] += usd
                        entity_activity[eid]["30d"]["txs"].append(tx_record)
                    if days_ago <= 90:
                        entity_activity[eid]["90d"][direction] += usd
                        entity_activity[eid]["90d"]["txs"].append(tx_record)

            except Exception as e:
                print(f"Error checking {entity_id}: {e}")

    # Build results
    results = []
    for entity_id, data in entity_activity.items():
        net_7d = data["7d"]["received"] - data["7d"]["sent"]
        net_30d = data["30d"]["received"] - data["30d"]["sent"]
        net_90d = data["90d"]["received"] - data["90d"]["sent"]

        # Only include entities with meaningful activity
        if abs(net_30d) < 1000 and abs(net_90d) < 1000:
            continue

        # Sort transactions by timestamp
        all_txs = sorted(data["all_txs"], key=lambda x: x["timestamp"], reverse=True)

        results.append({
            "entity_id": entity_id,
            "name": data["name"],
            "type": data["type"],
            "is_tracked": data["is_tracked"],
            "is_market_maker": data["is_market_maker"],
            "net_7d": net_7d,
            "net_30d": net_30d,
            "net_90d": net_90d,
            "received_7d": data["7d"]["received"],
            "sent_7d": data["7d"]["sent"],
            "received_30d": data["30d"]["received"],
            "sent_30d": data["30d"]["sent"],
            "received_90d": data["90d"]["received"],
            "sent_90d": data["90d"]["sent"],
            "tx_count_7d": len(data["7d"]["txs"]),
            "tx_count_30d": len(data["30d"]["txs"]),
            "recent_txs": all_txs[:10],  # Last 10 transactions
        })

    # Sort by 30d net flow
    results.sort(key=lambda x: x["net_30d"], reverse=True)

    # Separate into categories
    accumulators = [r for r in results if r["net_30d"] > 0]
    sellers = [r for r in results if r["net_30d"] < 0]

    # Separate market makers from "smart money"
    smart_money_accum = [r for r in accumulators if not r["is_market_maker"]]
    smart_money_sellers = [r for r in sellers if not r["is_market_maker"]]
    mm_accum = [r for r in accumulators if r["is_market_maker"]]
    mm_sellers = [r for r in sellers if r["is_market_maker"]]

    # All transactions for the token (for timeline)
    all_transactions = []
    for data in entity_activity.values():
        for tx in data["all_txs"]:
            all_transactions.append({
                **tx,
                "entity": data["name"],
                "entity_type": data["type"],
            })
    all_transactions.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "token": token_symbol,
        "accumulators": accumulators,
        "sellers": sellers,
        "smart_money": {
            "accumulators": smart_money_accum,
            "sellers": smart_money_sellers,
        },
        "market_makers": {
            "accumulators": mm_accum,
            "sellers": mm_sellers,
        },
        "recent_transactions": all_transactions[:50],
        "summary": {
            "total_accumulated_30d": sum(r["net_30d"] for r in accumulators),
            "total_sold_30d": abs(sum(r["net_30d"] for r in sellers)),
            "accumulator_count": len(accumulators),
            "seller_count": len(sellers),
            "smart_money_accumulating": len(smart_money_accum),
            "smart_money_selling": len(smart_money_sellers),
            "total_entities": len(results),
        }
    }


@app.get("/api/fund/{fund_id}")
def get_fund_activity(fund_id: str):
    """Get comprehensive activity for a specific fund/entity."""
    all_entities = {**ENTITIES, **NOTABLE_TRADERS}
    fund_name = all_entities.get(fund_id, fund_id)

    # Fetch transfers for this fund
    transfers = fetch_fund_transfers(fund_id, limit=200, min_usd=1000)

    if not transfers:
        return {
            "fund_id": fund_id,
            "name": fund_name,
            "tokens": [],
            "transactions": [],
            "stats": {"received": 0, "sent": 0, "net": 0, "tx_count": 0, "exchange_sent": 0, "unique_tokens": 0},
        }

    # Process transfers
    token_data = {}
    transactions = []

    for tx in transfers:
        usd = tx.get("historicalUSD", 0) or 0
        if usd < 1000:
            continue

        ts = tx.get("blockTimestamp", "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            days_ago = (datetime.now(dt.tzinfo) - dt).days
            time_ago = f"{days_ago}d ago" if days_ago > 0 else "today"
        except:
            days_ago = 999
            time_ago = "?"

        to_entity = (tx.get("toAddress") or {}).get("arkhamEntity") or {}
        from_entity = (tx.get("fromAddress") or {}).get("arkhamEntity") or {}

        if to_entity.get("id") == fund_id:
            direction = "received"
            counterparty = from_entity.get("name") or "Unknown"
            counterparty_type = from_entity.get("type") or ""
        elif from_entity.get("id") == fund_id:
            direction = "sent"
            counterparty = to_entity.get("name") or "Unknown"
            counterparty_type = to_entity.get("type") or ""
        else:
            continue

        token = (tx.get("tokenSymbol") or "???").upper()
        is_exchange = counterparty_type == "cex"

        # Track token activity
        if token not in token_data:
            token_data[token] = {"received": 0, "sent": 0}

        token_data[token][direction] += usd

        transactions.append({
            "timestamp": ts,
            "time_ago": time_ago,
            "days_ago": days_ago,
            "direction": direction,
            "token": token,
            "amount": tx.get("unitValue", 0) or 0,
            "usd": usd,
            "counterparty": counterparty,
            "counterparty_type": counterparty_type,
            "is_exchange": is_exchange,
            "chain": tx.get("chain", ""),
        })

    # Build token summary
    tokens = []
    for token, data in token_data.items():
        net = data["received"] - data["sent"]
        tokens.append({
            "token": token,
            "received": data["received"],
            "sent": data["sent"],
            "net": net,
        })
    tokens.sort(key=lambda x: abs(x["net"]), reverse=True)

    # Calculate stats
    total_received = sum(t["received"] for t in tokens)
    total_sent = sum(t["sent"] for t in tokens)
    exchange_sent = sum(tx["usd"] for tx in transactions if tx["direction"] == "sent" and tx["is_exchange"])

    return {
        "fund_id": fund_id,
        "name": fund_name,
        "is_tracked": fund_id in ENTITIES or fund_id in NOTABLE_TRADERS,
        "tokens": tokens[:20],
        "transactions": transactions[:50],
        "stats": {
            "received": total_received,
            "sent": total_sent,
            "net": total_received - total_sent,
            "tx_count": len(transactions),
            "exchange_sent": exchange_sent,
            "unique_tokens": len(tokens),
        },
    }


def fetch_fund_portfolio(fund_id: str) -> dict:
    """Fetch portfolio/holdings for a fund from Arkham."""
    try:
        r = httpx.get(
            f"{BASE_URL}/portfolio/entity/{fund_id}",
            headers={"API-Key": get_api_key()},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"Error fetching portfolio for {fund_id}: {e}")
    return {}


def calculate_fund_pnl(fund_id: str, fund_name: str) -> dict:
    """Calculate P/L for a fund based on transfers and current holdings."""
    # Fetch transfers to calculate cost basis
    transfers = fetch_fund_transfers(fund_id, limit=500, min_usd=100)

    # Fetch current portfolio
    portfolio = fetch_fund_portfolio(fund_id)

    # Track token flows from transfers
    token_flows = {}  # token -> {bought_usd, sold_usd, bought_amount, sold_amount}

    for tx in transfers:
        token = (tx.get("tokenSymbol") or "").upper()
        if not token:
            continue

        usd = tx.get("historicalUSD", 0) or 0
        amount = tx.get("unitValue", 0) or 0

        to_entity = (tx.get("toAddress") or {}).get("arkhamEntity") or {}
        from_entity = (tx.get("fromAddress") or {}).get("arkhamEntity") or {}

        if token not in token_flows:
            token_flows[token] = {"bought_usd": 0, "sold_usd": 0, "bought_amount": 0, "sold_amount": 0}

        if to_entity.get("id") == fund_id:
            # Received = bought
            token_flows[token]["bought_usd"] += usd
            token_flows[token]["bought_amount"] += amount
        elif from_entity.get("id") == fund_id:
            # Sent = sold
            token_flows[token]["sold_usd"] += usd
            token_flows[token]["sold_amount"] += amount

    # Parse portfolio for current holdings
    current_holdings = {}
    portfolio_value = 0

    # Portfolio structure varies - try different formats
    holdings_list = portfolio.get("holdings", []) or portfolio.get("tokens", []) or []
    if isinstance(portfolio, dict) and "chains" in portfolio:
        # Flatten chain-based portfolio
        for chain_data in portfolio.get("chains", {}).values():
            if isinstance(chain_data, dict):
                holdings_list.extend(chain_data.get("tokens", []))

    for holding in holdings_list:
        if isinstance(holding, dict):
            token = (holding.get("symbol") or holding.get("token", {}).get("symbol") or "").upper()
            value = holding.get("valueUsd") or holding.get("value") or holding.get("usdValue") or 0
            amount = holding.get("amount") or holding.get("balance") or 0

            if token and value > 100:  # Only significant holdings
                current_holdings[token] = {
                    "amount": amount,
                    "current_value": value,
                }
                portfolio_value += value

    # Calculate P/L per token
    token_pnl = []
    total_cost_basis = 0
    total_current_value = 0
    total_realized_pnl = 0

    for token, flows in token_flows.items():
        net_amount = flows["bought_amount"] - flows["sold_amount"]
        cost_basis = flows["bought_usd"]
        proceeds = flows["sold_usd"]

        # Realized P/L from sales
        if flows["sold_amount"] > 0 and flows["bought_amount"] > 0:
            avg_cost = flows["bought_usd"] / flows["bought_amount"] if flows["bought_amount"] > 0 else 0
            realized_pnl = proceeds - (avg_cost * flows["sold_amount"])
        else:
            realized_pnl = 0

        # Current value from portfolio or estimate
        current_value = 0
        if token in current_holdings:
            current_value = current_holdings[token]["current_value"]
        elif net_amount > 0 and flows["bought_amount"] > 0:
            # Estimate: use avg buy price as current price (conservative)
            avg_price = flows["bought_usd"] / flows["bought_amount"]
            current_value = net_amount * avg_price

        # Unrealized P/L
        remaining_cost_basis = cost_basis * (net_amount / flows["bought_amount"]) if flows["bought_amount"] > 0 else 0
        unrealized_pnl = current_value - remaining_cost_basis if net_amount > 0 else 0

        if abs(cost_basis) > 1000 or abs(current_value) > 1000:
            token_pnl.append({
                "token": token,
                "bought_usd": flows["bought_usd"],
                "sold_usd": flows["sold_usd"],
                "net_amount": net_amount,
                "cost_basis": remaining_cost_basis,
                "current_value": current_value,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "total_pnl": realized_pnl + unrealized_pnl,
            })
            total_cost_basis += remaining_cost_basis
            total_current_value += current_value
            total_realized_pnl += realized_pnl

    token_pnl.sort(key=lambda x: abs(x["total_pnl"]), reverse=True)

    return {
        "fund_id": fund_id,
        "name": fund_name,
        "token_count": len([t for t in token_pnl if t["current_value"] > 0]),
        "portfolio_value": portfolio_value if portfolio_value > 0 else total_current_value,
        "total_cost_basis": total_cost_basis,
        "total_current_value": total_current_value,
        "total_realized_pnl": total_realized_pnl,
        "total_unrealized_pnl": total_current_value - total_cost_basis,
        "total_pnl": total_realized_pnl + (total_current_value - total_cost_basis),
        "tokens": token_pnl[:15],
    }


@app.get("/api/fund-pnl")
def get_all_fund_pnl():
    """Get P/L data for all tracked funds."""
    results = []

    # Fetch P/L for each fund concurrently
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(calculate_fund_pnl, fid, fname): fid for fid, fname in ENTITIES.items()}
        for future in as_completed(futures):
            fund_id = futures[future]
            try:
                result = future.result()
                if result["total_cost_basis"] > 0 or result["portfolio_value"] > 0:
                    results.append(result)
            except Exception as e:
                print(f"Error calculating P/L for {fund_id}: {e}")

    # Sort by portfolio value
    results.sort(key=lambda x: x["portfolio_value"], reverse=True)

    return {
        "funds": results,
        "summary": {
            "total_funds": len(results),
            "total_portfolio_value": sum(f["portfolio_value"] for f in results),
            "total_pnl": sum(f["total_pnl"] for f in results),
        }
    }


@app.get("/api/fund-pnl/{fund_id}")
def get_fund_pnl(fund_id: str):
    """Get detailed P/L for a specific fund."""
    fund_name = ENTITIES.get(fund_id, NOTABLE_TRADERS.get(fund_id, fund_id))
    return calculate_fund_pnl(fund_id, fund_name)


def generate_signals():
    """Generate all actionable signals from cached activity data."""
    with cache_lock:
        if cache["activity"] is None:
            return None
        data = cache["activity"].copy()

    activity = data.get("activity", [])
    if not activity:
        return None

    now = datetime.now()
    signals = {
        "accumulation_alerts": [],  # 3+ funds buying same token in 24h
        "exit_signals": [],         # Multiple funds sending to exchanges
        "conviction_plays": [],     # Funds adding to existing positions
        "pre_pump": [],             # Unusual inflow spikes
        "smart_money_buys": [],     # What profitable traders are buying
    }

    # Group activity by token
    token_activity = {}
    for tx in activity:
        token = tx.get("token", "")
        if not token or token in ["USDT", "USDC", "DAI", "USDE"]:  # Skip stables
            continue

        if token not in token_activity:
            token_activity[token] = {"buys": [], "sells": [], "exchange_sells": []}

        if tx.get("action") == "Received":
            token_activity[token]["buys"].append(tx)
        else:
            token_activity[token]["sells"].append(tx)
            if tx.get("is_exchange"):
                token_activity[token]["exchange_sells"].append(tx)

    # 1. ACCUMULATION ALERTS - 3+ funds buying same token in 24h
    for token, data in token_activity.items():
        buys = data["buys"]
        # Filter to last 24h
        recent_buys = [b for b in buys if "h" in b.get("time_ago", "") or b.get("time_ago") == "today"]

        unique_funds = list(set(b["fund"] for b in recent_buys))
        if len(unique_funds) >= 3:
            total_usd = sum(b["usd"] for b in recent_buys)
            signals["accumulation_alerts"].append({
                "token": token,
                "fund_count": len(unique_funds),
                "funds": unique_funds[:5],
                "total_usd": total_usd,
                "buys": len(recent_buys),
                "strength": "STRONG" if len(unique_funds) >= 5 else "MODERATE",
            })

    # Sort by fund count
    signals["accumulation_alerts"].sort(key=lambda x: x["fund_count"], reverse=True)

    # 2. EXIT SIGNALS - Multiple funds sending to exchanges
    for token, data in token_activity.items():
        exchange_sells = data["exchange_sells"]
        if len(exchange_sells) >= 2:
            unique_funds = list(set(s["fund"] for s in exchange_sells))
            if len(unique_funds) >= 2:
                total_usd = sum(s["usd"] for s in exchange_sells)
                signals["exit_signals"].append({
                    "token": token,
                    "fund_count": len(unique_funds),
                    "funds": unique_funds[:5],
                    "total_usd": total_usd,
                    "severity": "HIGH" if len(unique_funds) >= 3 or total_usd >= 1000000 else "MEDIUM",
                })

    signals["exit_signals"].sort(key=lambda x: x["total_usd"], reverse=True)

    # 3. CONVICTION PLAYS - Funds with multiple buys of same token (adding to position)
    fund_token_buys = {}
    for tx in activity:
        if tx.get("action") != "Received":
            continue
        token = tx.get("token", "")
        if not token or token in ["USDT", "USDC", "DAI", "USDE"]:
            continue

        fund = tx.get("fund", "")
        key = f"{fund}|{token}"
        if key not in fund_token_buys:
            fund_token_buys[key] = {"fund": fund, "fund_id": tx.get("fund_id"), "token": token, "buys": [], "total_usd": 0}
        fund_token_buys[key]["buys"].append(tx)
        fund_token_buys[key]["total_usd"] += tx.get("usd", 0)

    for key, data in fund_token_buys.items():
        if len(data["buys"]) >= 2 and data["total_usd"] >= 50000:
            signals["conviction_plays"].append({
                "fund": data["fund"],
                "fund_id": data["fund_id"],
                "token": data["token"],
                "buy_count": len(data["buys"]),
                "total_usd": data["total_usd"],
                "conviction": "HIGH" if len(data["buys"]) >= 3 or data["total_usd"] >= 500000 else "MEDIUM",
            })

    signals["conviction_plays"].sort(key=lambda x: x["total_usd"], reverse=True)

    # 4. PRE-PUMP DETECTION - Tokens with high buy/sell ratio and multiple funds
    for token, data in token_activity.items():
        buy_usd = sum(b["usd"] for b in data["buys"])
        sell_usd = sum(s["usd"] for s in data["sells"])

        if buy_usd < 100000:  # Minimum threshold
            continue

        unique_buyers = len(set(b["fund"] for b in data["buys"]))

        # Strong buy signal: high buy/sell ratio + multiple funds
        if sell_usd > 0:
            ratio = buy_usd / sell_usd
        else:
            ratio = 10 if buy_usd > 0 else 0

        if ratio >= 3 and unique_buyers >= 2:
            signals["pre_pump"].append({
                "token": token,
                "buy_usd": buy_usd,
                "sell_usd": sell_usd,
                "ratio": round(ratio, 1),
                "unique_buyers": unique_buyers,
                "funds": list(set(b["fund"] for b in data["buys"]))[:5],
                "signal_strength": "STRONG" if ratio >= 5 and unique_buyers >= 3 else "MODERATE",
            })

    signals["pre_pump"].sort(key=lambda x: x["ratio"] * x["unique_buyers"], reverse=True)

    # 5. SMART MONEY BUYS - Recent buys from notable traders
    notable_ids = set(NOTABLE_TRADERS.keys())
    smart_buys = []
    for tx in activity:
        if tx.get("action") != "Received":
            continue
        if tx.get("fund_id") in notable_ids:
            token = tx.get("token", "")
            if token and token not in ["USDT", "USDC", "DAI", "USDE"]:
                smart_buys.append({
                    "trader": tx.get("fund"),
                    "trader_id": tx.get("fund_id"),
                    "token": token,
                    "usd": tx.get("usd", 0),
                    "time_ago": tx.get("time_ago"),
                })

    signals["smart_money_buys"] = smart_buys[:20]

    return signals


@app.get("/api/signals")
def get_signals():
    """Get all actionable trading signals."""
    signals = generate_signals()
    if signals is None:
        return {
            "loading": True,
            "message": "Cache is building, please wait...",
        }
    return {
        "signals": signals,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "accumulation_alerts": len(signals["accumulation_alerts"]),
            "exit_signals": len(signals["exit_signals"]),
            "conviction_plays": len(signals["conviction_plays"]),
            "pre_pump": len(signals["pre_pump"]),
            "smart_money_buys": len(signals["smart_money_buys"]),
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


@app.get("/pnl", response_class=HTMLResponse)
def pnl_page():
    """Serve the Fund P/L page."""
    html_path = BASE_DIR / "templates" / "pnl.html"
    return html_path.read_text()


@app.get("/signals", response_class=HTMLResponse)
def signals_page():
    """Serve the Signals page."""
    html_path = BASE_DIR / "templates" / "signals.html"
    return html_path.read_text()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
