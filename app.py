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
    elif from_entity.get("id") == fund_id:
        action = "Sent"
        counterparty = to_entity.get("name") or "Unknown"
    else:
        return None

    ts = tx.get("blockTimestamp", "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        time_ago = datetime.now(dt.tzinfo) - dt
        if time_ago.days > 0:
            time_str = f"{time_ago.days}d ago"
        elif time_ago.seconds > 3600:
            time_str = f"{time_ago.seconds // 3600}h ago"
        else:
            time_str = f"{time_ago.seconds // 60}m ago"
    except:
        time_str = "?"

    return {
        "timestamp": ts,
        "time_ago": time_str,
        "fund_id": fund_id,
        "fund": fund_name,
        "action": action,
        "token": (tx.get("tokenSymbol") or "???").upper(),
        "token_name": tx.get("tokenName") or "",
        "amount": tx.get("unitValue", 0) or 0,
        "usd": usd,
        "counterparty": counterparty[:25],
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

    token_flows = {}
    for a in all_activity:
        token = a["token"]
        if token not in token_flows:
            token_flows[token] = {"received": 0, "sent": 0}
        if a["action"] == "Received":
            token_flows[token]["received"] += a["usd"]
        else:
            token_flows[token]["sent"] += a["usd"]

    top_tokens = sorted(
        [
            {"token": t, "net": d["received"] - d["sent"], "received": d["received"], "sent": d["sent"]}
            for t, d in token_flows.items()
        ],
        key=lambda x: abs(x["net"]),
        reverse=True,
    )[:10]

    return {
        "activity": all_activity[:200],
        "stats": {
            "total_received": total_received,
            "total_sent": total_sent,
            "net_flow": total_received - total_sent,
            "transaction_count": len(all_activity),
        },
        "top_tokens": top_tokens,
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
