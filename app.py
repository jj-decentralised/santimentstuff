"""Fund Activity Tracker - What are funds doing today?"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

# Config
BASE_URL = "https://api.arkm.com"
BASE_DIR = Path(__file__).parent

# Entities to track - expanded list
ENTITIES = {
    # VCs & Funds
    "jump-trading": "Jump Crypto",
    "wintermute": "Wintermute",
    "galaxy-digital": "Galaxy Digital",
    "dragonfly-capital": "Dragonfly",
    "a16z": "a16z",
    "paradigm-capital": "Paradigm",
    "pantera-capital": "Pantera",
    "polychain-capital": "Polychain",
    "blockchain-capital": "Blockchain Capital",
    "multicoin-capital": "Multicoin",
    "framework-ventures": "Framework",
    "placeholder-vc": "Placeholder",
    "variant-fund": "Variant",
    "electric-capital": "Electric Capital",
    "1confirmation": "1confirmation",
    "spartan-group": "Spartan",
    "animoca-brands": "Animoca",
    "binance-labs": "Binance Labs",
    "grayscale": "Grayscale",
    "cumberland": "Cumberland",
    "genesis-trading": "Genesis",
    "dwf-labs": "DWF Labs",
    "alameda-research": "Alameda",
    "three-arrows-capital": "3AC",
    "digital-currency-group": "DCG",
    "ftx": "FTX",
    "mirana-ventures": "Mirana",
    "fabric-ventures": "Fabric",
    "delphi-digital": "Delphi",
    "maven-11": "Maven 11",
    "mechanism-capital": "Mechanism",
    "nascent": "Nascent",
    "paradigm-fund": "Paradigm Fund",
    "ribbit-capital": "Ribbit",
    "sequoia-capital": "Sequoia",
    "andreessen-horowitz": "a16z (AH)",
    # Market Makers & Trading
    "b2c2": "B2C2",
    "gsr": "GSR",
    "amber-group": "Amber",
    "akuna-capital": "Akuna",
    "flow-traders": "Flow Traders",
    "jane-street": "Jane Street",
    "susquehanna": "Susquehanna",
    # Institutional
    "coinbase": "Coinbase",
    "circle": "Circle",
    "bitgo": "BitGo",
    "anchorage": "Anchorage",
    "fireblocks": "Fireblocks",
    "fidelity": "Fidelity",
    "blackrock": "BlackRock",
    # Exchanges (for flow tracking)
    "binance": "Binance",
    "kraken": "Kraken",
    "okx": "OKX",
    "bybit": "Bybit",
    "bitfinex": "Bitfinex",
    # Notable individuals
    "vitalik-buterin": "Vitalik",
    "justin-sun": "Justin Sun",
    "cz-binance": "CZ",
    "brian-armstrong": "Brian Armstrong",
    "do-kwon": "Do Kwon",
    "arthur-hayes": "Arthur Hayes",
    "su-zhu": "Su Zhu",
    "kyle-davies": "Kyle Davies",
    # Protocols & Treasuries
    "ethereum-foundation": "Ethereum Foundation",
    "solana-foundation": "Solana Foundation",
    "uniswap": "Uniswap",
    "aave": "Aave",
    "compound": "Compound",
    "maker": "MakerDAO",
    "lido": "Lido",
}

app = FastAPI(title="Fund Activity Tracker")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_api_key():
    return os.environ.get("ARKHAM_API_KEY", "")


def fetch_fund_transfers(fund_id: str, limit: int = 50) -> list:
    """Fetch recent transfers for a fund."""
    try:
        r = httpx.get(
            f"{BASE_URL}/transfers",
            params={"base": fund_id, "limit": limit, "sortDir": "desc"},
            headers={"API-Key": get_api_key()},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("transfers", [])
    except Exception as e:
        print(f"Error fetching {fund_id}: {e}")
        return []


def parse_transfer(tx: dict, fund_id: str, fund_name: str) -> dict | None:
    """Parse a transfer into a clean activity item."""
    # Skip if no USD value
    usd = tx.get("historicalUSD", 0) or 0
    if usd < 1000:  # Skip small transfers
        return None

    # Determine direction
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

    # Parse timestamp
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
        dt = datetime.now()

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


@app.get("/api/activity")
def get_activity(
    min_usd: int = Query(10000, description="Minimum USD value"),
    limit_per_entity: int = Query(15, description="Max transfers per entity"),
):
    """Get recent activity across all entities."""
    all_activity = []

    for entity_id, entity_name in ENTITIES.items():
        transfers = fetch_fund_transfers(entity_id, limit=limit_per_entity)
        for tx in transfers:
            item = parse_transfer(tx, entity_id, entity_name)
            if item and item["usd"] >= min_usd:
                all_activity.append(item)

    # Sort by timestamp desc
    all_activity.sort(key=lambda x: x["timestamp"], reverse=True)

    # Aggregate stats
    total_received = sum(a["usd"] for a in all_activity if a["action"] == "Received")
    total_sent = sum(a["usd"] for a in all_activity if a["action"] == "Sent")

    # Token summary
    token_flows = {}
    for a in all_activity:
        token = a["token"]
        if token not in token_flows:
            token_flows[token] = {"received": 0, "sent": 0}
        if a["action"] == "Received":
            token_flows[token]["received"] += a["usd"]
        else:
            token_flows[token]["sent"] += a["usd"]

    # Top tokens by net flow
    top_tokens = sorted(
        [
            {"token": t, "net": d["received"] - d["sent"], "received": d["received"], "sent": d["sent"]}
            for t, d in token_flows.items()
        ],
        key=lambda x: abs(x["net"]),
        reverse=True,
    )[:10]

    return {
        "activity": all_activity[:200],  # Limit response
        "stats": {
            "total_received": total_received,
            "total_sent": total_sent,
            "net_flow": total_received - total_sent,
            "transaction_count": len(all_activity),
        },
        "top_tokens": top_tokens,
    }


@app.get("/api/token/{token_symbol}")
def get_token_activity(token_symbol: str):
    """Get accumulation/distribution for a specific token across all entities."""
    token_symbol = token_symbol.upper()

    # Track activity by entity and time period
    entity_activity = {}

    for entity_id, entity_name in ENTITIES.items():
        transfers = fetch_fund_transfers(entity_id, limit=100)

        for tx in transfers:
            tx_token = (tx.get("tokenSymbol") or "").upper()
            if tx_token != token_symbol:
                continue

            usd = tx.get("historicalUSD", 0) or 0
            if usd < 1000:
                continue

            # Parse timestamp
            ts = tx.get("blockTimestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                days_ago = (datetime.now(dt.tzinfo) - dt).days
            except:
                continue

            # Determine direction
            to_entity = (tx.get("toAddress") or {}).get("arkhamEntity") or {}
            from_entity = (tx.get("fromAddress") or {}).get("arkhamEntity") or {}

            if to_entity.get("id") == entity_id:
                direction = "received"
            elif from_entity.get("id") == entity_id:
                direction = "sent"
            else:
                continue

            # Initialize entity tracking
            if entity_id not in entity_activity:
                entity_activity[entity_id] = {
                    "name": entity_name,
                    "7d": {"received": 0, "sent": 0},
                    "30d": {"received": 0, "sent": 0},
                    "90d": {"received": 0, "sent": 0},
                }

            # Add to appropriate time buckets
            if days_ago <= 7:
                entity_activity[entity_id]["7d"][direction] += usd
            if days_ago <= 30:
                entity_activity[entity_id]["30d"][direction] += usd
            if days_ago <= 90:
                entity_activity[entity_id]["90d"][direction] += usd

    # Calculate net flows and categorize
    results = []
    for entity_id, data in entity_activity.items():
        net_7d = data["7d"]["received"] - data["7d"]["sent"]
        net_30d = data["30d"]["received"] - data["30d"]["sent"]
        net_90d = data["90d"]["received"] - data["90d"]["sent"]

        # Only include if there's meaningful activity
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

    # Sort by 30d net flow
    results.sort(key=lambda x: x["net_30d"], reverse=True)

    # Separate accumulators and sellers
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
    return {"status": "ok", "api_key_set": bool(key), "entities_tracked": len(ENTITIES)}


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the dashboard."""
    html_path = BASE_DIR / "templates" / "dashboard.html"
    return html_path.read_text()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
