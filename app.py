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

# Major funds to track
FUNDS = {
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
    "coinbase": "Coinbase",
    "grayscale": "Grayscale",
    "cumberland": "Cumberland",
    "genesis-trading": "Genesis",
    "dwf-labs": "DWF Labs",
    "alameda-research": "Alameda",
    "three-arrows-capital": "3AC",
    "circle": "Circle",
    "digital-currency-group": "DCG",
    "ftx": "FTX",
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
    limit_per_fund: int = Query(20, description="Max transfers per fund"),
):
    """Get recent activity across all funds."""
    all_activity = []

    for fund_id, fund_name in FUNDS.items():
        transfers = fetch_fund_transfers(fund_id, limit=limit_per_fund)
        for tx in transfers:
            item = parse_transfer(tx, fund_id, fund_name)
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


@app.get("/health")
def health():
    key = get_api_key()
    return {"status": "ok", "api_key_set": bool(key), "funds_tracked": len(FUNDS)}


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the dashboard."""
    html_path = BASE_DIR / "templates" / "dashboard.html"
    return html_path.read_text()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
