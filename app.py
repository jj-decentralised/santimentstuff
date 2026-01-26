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
    "swaps": None,
    "entity_profiles": None,
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


def fetch_fund_swaps(fund_id: str, limit: int = 50) -> list:
    """Fetch recent DEX swaps for a fund - actual trading activity."""
    try:
        r = httpx.get(
            f"{BASE_URL}/swaps",
            params={
                "base": fund_id,
                "limit": limit,
            },
            headers={"API-Key": get_api_key()},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("swaps", [])
    except httpx.TimeoutException:
        print(f"Timeout fetching swaps for {fund_id}")
        return []
    except Exception as e:
        print(f"Error fetching swaps for {fund_id}: {e}")
        return []


def fetch_entity_intelligence(entity_id: str) -> dict:
    """Fetch entity intelligence including whale/early holder/governance tags."""
    try:
        r = httpx.get(
            f"{BASE_URL}/intelligence/entity/{entity_id}",
            headers={"API-Key": get_api_key()},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()

            # Parse populatedTags for whale status, early holder, governance
            tags = data.get("populatedTags", [])

            whale_tokens = []
            early_tokens = []
            governance_protocols = []

            for tag in tags:
                tag_type = tag.get("type", "")
                tag_name = tag.get("name", "")

                if tag_type == "whale" or "whale" in tag_name.lower():
                    # Extract token from tag like "UNI Whale"
                    token = tag_name.replace(" Whale", "").strip()
                    if token:
                        whale_tokens.append(token)

                elif tag_type == "early-token-holder" or "early" in tag_name.lower():
                    # Extract token from tag like "Early UNI Holder"
                    token = tag_name.replace("Early ", "").replace(" Holder", "").strip()
                    if token:
                        early_tokens.append(token)

                elif tag_type in ["governance-voter", "governance-delegatee"] or "governance" in tag_name.lower():
                    # Extract protocol from governance tags
                    protocol = tag_name.replace(" Governance Voter", "").replace(" Governance Delegatee", "").strip()
                    if protocol:
                        governance_protocols.append(protocol)

            return {
                "entity_id": entity_id,
                "name": data.get("name", entity_id),
                "type": data.get("type", ""),
                "whale_tokens": whale_tokens,
                "early_tokens": early_tokens,
                "governance_protocols": governance_protocols,
                "all_tags": [t.get("name", "") for t in tags],
                "address_count": len(data.get("addresses", [])),
            }
    except Exception as e:
        print(f"Error fetching intelligence for {entity_id}: {e}")

    return {"entity_id": entity_id, "whale_tokens": [], "early_tokens": [], "governance_protocols": [], "all_tags": []}


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


# Max age for transactions (30 days in hours)
MAX_TX_AGE_HOURS = 30 * 24  # 720 hours


def parse_swap(swap: dict, fund_id: str, fund_name: str) -> dict | None:
    """Parse a DEX swap into a clean activity item. Filters out swaps older than 30 days."""
    usd = swap.get("historicalUSD", 0) or 0
    if usd < 1000:
        return None

    ts = swap.get("blockTimestamp", "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        time_ago = datetime.now(dt.tzinfo) - dt
        hours_ago = time_ago.total_seconds() / 3600
        days_ago = time_ago.days

        # FILTER: Skip swaps older than 30 days
        if days_ago > 30:
            return None

        if time_ago.days > 0:
            time_str = f"{time_ago.days}d ago"
        elif time_ago.seconds > 3600:
            time_str = f"{time_ago.seconds // 3600}h ago"
        else:
            time_str = f"{time_ago.seconds // 60}m ago"
    except:
        return None

    # token0 = sold token, token1 = bought token (standard DEX convention)
    token_sold = (swap.get("token0Symbol") or "???").upper()
    token_bought = (swap.get("token1Symbol") or "???").upper()
    amount_sold = swap.get("unitValue0", 0) or 0
    amount_bought = swap.get("unitValue1", 0) or 0

    # Get DEX info
    dex_entity = swap.get("fromAddress", {}).get("arkhamEntity") or {}
    dex_name = dex_entity.get("name", "Unknown DEX")

    # Determine if this is a buy or sell of non-stable tokens
    stables = {"USDT", "USDC", "DAI", "USDE", "BUSD", "TUSD", "FRAX"}

    if token_bought in stables and token_sold not in stables:
        # Selling crypto for stables = SELL signal
        action = "Sold"
        primary_token = token_sold
        primary_amount = amount_sold
        secondary_token = token_bought
    elif token_sold in stables and token_bought not in stables:
        # Buying crypto with stables = BUY signal
        action = "Bought"
        primary_token = token_bought
        primary_amount = amount_bought
        secondary_token = token_sold
    elif token_sold in stables and token_bought in stables:
        # Stable-to-stable swap, skip
        return None
    else:
        # Crypto to crypto swap - consider it buying token1
        action = "Swapped"
        primary_token = token_bought
        primary_amount = amount_bought
        secondary_token = token_sold

    return {
        "type": "swap",
        "timestamp": ts,
        "time_ago": time_str,
        "hours_ago": hours_ago,
        "days_ago": days_ago,
        "fund_id": fund_id,
        "fund": fund_name,
        "action": action,
        "token": primary_token,
        "token_sold": token_sold,
        "token_bought": token_bought,
        "amount_sold": amount_sold,
        "amount_bought": amount_bought,
        "usd": usd,
        "dex": dex_name,
        "chain": swap.get("chain", ""),
        "tx_hash": swap.get("transactionHash", ""),
        "category": TOKEN_CATEGORIES.get(primary_token, "other"),
    }


def parse_transfer(tx: dict, fund_id: str, fund_name: str) -> dict | None:
    """Parse a transfer into a clean activity item. Filters out transactions older than 30 days."""
    usd = tx.get("historicalUSD", 0) or 0
    if usd < 1000:
        return None

    # Parse timestamp first to filter old transactions
    ts = tx.get("blockTimestamp", "")
    hours_ago = 0
    days_ago = 0
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        time_ago = datetime.now(dt.tzinfo) - dt
        hours_ago = time_ago.total_seconds() / 3600
        days_ago = time_ago.days

        # FILTER: Skip transactions older than 30 days
        if days_ago > 30:
            return None

        if time_ago.days > 0:
            time_str = f"{time_ago.days}d ago"
        elif time_ago.seconds > 3600:
            time_str = f"{time_ago.seconds // 3600}h ago"
        else:
            time_str = f"{time_ago.seconds // 60}m ago"
    except:
        time_str = "?"
        # Skip if we can't parse the timestamp
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


def fetch_entity_swaps(entity_id: str, entity_name: str, limit: int = 50) -> list:
    """Fetch and parse swaps for a single entity."""
    results = []
    try:
        swaps = fetch_fund_swaps(entity_id, limit=limit)
        for swap in swaps:
            item = parse_swap(swap, entity_id, entity_name)
            if item:
                results.append(item)
    except Exception as e:
        print(f"Error processing swaps for {entity_id}: {e}")
    return results


def build_swaps_data(limit_per_entity: int = 100) -> dict:
    """Build DEX swaps data from all tracked entities."""
    all_swaps = []

    # Fetch swaps from all entities concurrently
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_entity_swaps, eid, ename, limit_per_entity): eid
            for eid, ename in ENTITIES.items()
        }
        for future in as_completed(futures):
            entity_id = futures[future]
            try:
                results = future.result()
                all_swaps.extend(results)
                if results:
                    print(f"  Fetched {len(results)} swaps from {entity_id}")
            except Exception as e:
                print(f"  Failed swaps {entity_id}: {e}")

    all_swaps.sort(key=lambda x: x["timestamp"], reverse=True)

    # Group swaps by token (what they bought)
    token_swaps = {}
    for swap in all_swaps:
        token = swap.get("token", "")
        if not token:
            continue

        if token not in token_swaps:
            token_swaps[token] = {"buys": [], "sells": [], "total_buy_usd": 0, "total_sell_usd": 0, "funds_buying": set(), "funds_selling": set()}

        if swap["action"] in ["Bought", "Swapped"]:
            token_swaps[token]["buys"].append(swap)
            token_swaps[token]["total_buy_usd"] += swap["usd"]
            token_swaps[token]["funds_buying"].add(swap["fund"])
        elif swap["action"] == "Sold":
            token_swaps[token]["sells"].append(swap)
            token_swaps[token]["total_sell_usd"] += swap["usd"]
            token_swaps[token]["funds_selling"].add(swap["fund"])

    # Top tokens by swap activity
    token_summary = []
    for token, data in token_swaps.items():
        net = data["total_buy_usd"] - data["total_sell_usd"]
        token_summary.append({
            "token": token,
            "buy_usd": data["total_buy_usd"],
            "sell_usd": data["total_sell_usd"],
            "net_usd": net,
            "buy_count": len(data["buys"]),
            "sell_count": len(data["sells"]),
            "funds_buying": list(data["funds_buying"]),
            "funds_selling": list(data["funds_selling"]),
            "buyer_count": len(data["funds_buying"]),
            "seller_count": len(data["funds_selling"]),
            "signal": "BUY" if net > 0 and len(data["funds_buying"]) > len(data["funds_selling"]) else "SELL" if net < 0 else "NEUTRAL",
        })

    token_summary.sort(key=lambda x: x["buy_usd"] + x["sell_usd"], reverse=True)

    # Stats
    total_buys = sum(s["usd"] for s in all_swaps if s["action"] in ["Bought", "Swapped"])
    total_sells = sum(s["usd"] for s in all_swaps if s["action"] == "Sold")

    return {
        "swaps": all_swaps[:200],
        "token_summary": token_summary[:20],
        "stats": {
            "total_swaps": len(all_swaps),
            "total_buy_volume": total_buys,
            "total_sell_volume": total_sells,
            "net_flow": total_buys - total_sells,
            "tokens_traded": len(token_swaps),
            "active_funds": len(set(s["fund"] for s in all_swaps)),
        },
    }


def build_entity_profiles() -> dict:
    """Build entity intelligence profiles for all tracked funds."""
    profiles = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_entity_intelligence, eid): eid for eid in ENTITIES.keys()}
        for future in as_completed(futures):
            entity_id = futures[future]
            try:
                profile = future.result()
                profiles[entity_id] = profile
                if profile.get("whale_tokens") or profile.get("early_tokens"):
                    print(f"  Got profile for {entity_id}: {len(profile.get('whale_tokens', []))} whale tokens, {len(profile.get('early_tokens', []))} early tokens")
            except Exception as e:
                print(f"  Failed profile {entity_id}: {e}")

    # Aggregate by token: which funds are whales, which got early
    token_intelligence = {}
    for eid, profile in profiles.items():
        fund_name = ENTITIES.get(eid, eid)

        for token in profile.get("whale_tokens", []):
            if token not in token_intelligence:
                token_intelligence[token] = {"whale_funds": [], "early_funds": [], "governance_funds": []}
            token_intelligence[token]["whale_funds"].append({"fund_id": eid, "name": fund_name})

        for token in profile.get("early_tokens", []):
            if token not in token_intelligence:
                token_intelligence[token] = {"whale_funds": [], "early_funds": [], "governance_funds": []}
            token_intelligence[token]["early_funds"].append({"fund_id": eid, "name": fund_name})

        for protocol in profile.get("governance_protocols", []):
            if protocol not in token_intelligence:
                token_intelligence[protocol] = {"whale_funds": [], "early_funds": [], "governance_funds": []}
            token_intelligence[protocol]["governance_funds"].append({"fund_id": eid, "name": fund_name})

    return {
        "profiles": profiles,
        "token_intelligence": token_intelligence,
        "stats": {
            "total_profiles": len(profiles),
            "funds_with_whale_status": len([p for p in profiles.values() if p.get("whale_tokens")]),
            "funds_with_early_status": len([p for p in profiles.values() if p.get("early_tokens")]),
            "funds_with_governance": len([p for p in profiles.values() if p.get("governance_protocols")]),
        },
    }


def build_activity_data(min_usd: int = 10000, limit_per_entity: int = 200) -> dict:
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
    """Refresh the activity cache including swaps and entity profiles."""
    global cache
    with cache_lock:
        if cache["is_refreshing"]:
            return
        cache["is_refreshing"] = True

    try:
        print(f"[{datetime.now()}] Refreshing activity cache...")
        data = build_activity_data()

        print(f"[{datetime.now()}] Fetching DEX swaps...")
        swaps_data = build_swaps_data()

        print(f"[{datetime.now()}] Fetching entity profiles...")
        profiles_data = build_entity_profiles()

        with cache_lock:
            cache["activity"] = data
            cache["swaps"] = swaps_data
            cache["entity_profiles"] = profiles_data
            cache["last_updated"] = datetime.now()

        print(f"[{datetime.now()}] Cache refreshed: {len(data['activity'])} transfers, {len(swaps_data['swaps'])} swaps, {profiles_data['stats']['total_profiles']} profiles")
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
    limit_per_entity: int = Query(200, description="Max transfers per entity"),
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


@app.get("/api/swaps")
def get_swaps():
    """Get DEX swap activity from all tracked funds - actual trading signals."""
    with cache_lock:
        if cache["swaps"] is not None:
            data = cache["swaps"].copy()
            data["cached"] = True
            data["cache_age_seconds"] = (
                (datetime.now() - cache["last_updated"]).total_seconds()
                if cache["last_updated"]
                else None
            )
            return data
        is_refreshing = cache["is_refreshing"]

    return {
        "swaps": [],
        "token_summary": [],
        "stats": {"total_swaps": 0, "total_buy_volume": 0, "total_sell_volume": 0},
        "loading": True,
        "message": "Cache is building..." if is_refreshing else "Starting cache build...",
    }


@app.get("/api/fund/{fund_id}/profile")
def get_fund_profile(fund_id: str):
    """Get fund intelligence profile including whale status, early holder tags, and governance activity."""
    with cache_lock:
        profiles = cache.get("entity_profiles", {}).get("profiles", {})
        if fund_id in profiles:
            profile = profiles[fund_id].copy()

            # Add recent swap activity
            swaps = cache.get("swaps", {}).get("swaps", [])
            fund_swaps = [s for s in swaps if s.get("fund_id") == fund_id][:20]
            profile["recent_swaps"] = fund_swaps

            # Add recent transfers
            activity = cache.get("activity", {}).get("activity", [])
            fund_transfers = [a for a in activity if a.get("fund_id") == fund_id][:20]
            profile["recent_transfers"] = fund_transfers

            return profile

    # Not in cache - fetch fresh
    profile = fetch_entity_intelligence(fund_id)
    profile["name"] = ENTITIES.get(fund_id, NOTABLE_TRADERS.get(fund_id, fund_id))

    # Fetch recent swaps
    swaps = fetch_fund_swaps(fund_id, limit=20)
    profile["recent_swaps"] = [parse_swap(s, fund_id, profile["name"]) for s in swaps if parse_swap(s, fund_id, profile["name"])]

    return profile


@app.get("/api/alpha")
def get_alpha_signals():
    """Get high-conviction alpha signals - early holders buying new tokens, whale convergence, etc."""
    with cache_lock:
        profiles_data = cache.get("entity_profiles", {})
        swaps_data = cache.get("swaps", {})
        activity_data = cache.get("activity", {})

    if not profiles_data or not swaps_data:
        return {"loading": True, "message": "Cache is building..."}

    profiles = profiles_data.get("profiles", {})
    token_intel = profiles_data.get("token_intelligence", {})
    swaps = swaps_data.get("swaps", [])
    activity = activity_data.get("activity", [])

    signals = {
        "early_holder_alpha": [],      # Early holders buying NEW tokens
        "whale_convergence": [],       # Multiple whales accumulating same token
        "governance_conviction": [],   # Funds with governance activity adding to positions
        "new_whale_alert": [],         # Large accumulation by a single fund
        "smart_money_exit": [],        # Early holders/whales selling
    }

    # Build fund -> early tokens mapping
    fund_early_tokens = {}
    fund_whale_tokens = {}
    for fund_id, profile in profiles.items():
        fund_early_tokens[fund_id] = set(profile.get("early_tokens", []))
        fund_whale_tokens[fund_id] = set(profile.get("whale_tokens", []))

    # Group recent swaps by token
    token_recent_buys = {}
    token_recent_sells = {}
    for swap in swaps:
        if swap.get("action") in ["Bought", "Swapped"]:
            token = swap.get("token", "")
            if token not in token_recent_buys:
                token_recent_buys[token] = []
            token_recent_buys[token].append(swap)
        elif swap.get("action") == "Sold":
            token = swap.get("token", "")
            if token not in token_recent_sells:
                token_recent_sells[token] = []
            token_recent_sells[token].append(swap)

    # 1. EARLY HOLDER ALPHA - Early holders buying NEW tokens they don't already hold
    for swap in swaps:
        if swap.get("action") not in ["Bought", "Swapped"]:
            continue

        fund_id = swap.get("fund_id", "")
        token = swap.get("token", "")

        early_tokens = fund_early_tokens.get(fund_id, set())
        whale_tokens = fund_whale_tokens.get(fund_id, set())

        # Check if fund has early holder track record AND this is a NEW token for them
        if early_tokens and token not in early_tokens and token not in whale_tokens:
            signals["early_holder_alpha"].append({
                "fund": swap.get("fund"),
                "fund_id": fund_id,
                "token": token,
                "usd": swap.get("usd", 0),
                "time_ago": swap.get("time_ago"),
                "early_track_record": list(early_tokens)[:5],
                "signal_strength": "STRONG" if len(early_tokens) >= 3 else "MODERATE",
            })

    # Deduplicate and sort by USD
    seen = set()
    unique_alpha = []
    for sig in signals["early_holder_alpha"]:
        key = f"{sig['fund_id']}|{sig['token']}"
        if key not in seen:
            seen.add(key)
            unique_alpha.append(sig)
    signals["early_holder_alpha"] = sorted(unique_alpha, key=lambda x: x["usd"], reverse=True)[:20]

    # 2. WHALE CONVERGENCE - Multiple whale-status funds buying same token
    for token, buys in token_recent_buys.items():
        whale_buyers = []
        for buy in buys:
            fund_id = buy.get("fund_id", "")
            if fund_whale_tokens.get(fund_id):  # Fund has whale status in some tokens
                whale_buyers.append({
                    "fund": buy.get("fund"),
                    "fund_id": fund_id,
                    "usd": buy.get("usd", 0),
                    "whale_tokens": list(fund_whale_tokens.get(fund_id, []))[:3],
                })

        if len(whale_buyers) >= 2:
            total_usd = sum(b["usd"] for b in whale_buyers)
            signals["whale_convergence"].append({
                "token": token,
                "whale_count": len(whale_buyers),
                "total_usd": total_usd,
                "whales": whale_buyers[:5],
                "signal_strength": "STRONG" if len(whale_buyers) >= 3 else "MODERATE",
            })

    signals["whale_convergence"].sort(key=lambda x: x["whale_count"], reverse=True)

    # 3. SMART MONEY EXIT - Early holders or whales selling
    for swap in swaps:
        if swap.get("action") != "Sold":
            continue

        fund_id = swap.get("fund_id", "")
        token = swap.get("token", "")

        early_tokens = fund_early_tokens.get(fund_id, set())
        whale_tokens = fund_whale_tokens.get(fund_id, set())

        # Check if fund is early holder or whale in the token they're selling
        is_early = token in early_tokens
        is_whale = token in whale_tokens

        if is_early or is_whale:
            signals["smart_money_exit"].append({
                "fund": swap.get("fund"),
                "fund_id": fund_id,
                "token": token,
                "usd": swap.get("usd", 0),
                "time_ago": swap.get("time_ago"),
                "is_early_holder": is_early,
                "is_whale": is_whale,
                "severity": "HIGH" if is_early else "MEDIUM",
            })

    signals["smart_money_exit"].sort(key=lambda x: x["usd"], reverse=True)
    signals["smart_money_exit"] = signals["smart_money_exit"][:20]

    # 4. NEW WHALE ALERT - Large single-fund accumulation
    fund_token_totals = {}
    for swap in swaps:
        if swap.get("action") not in ["Bought", "Swapped"]:
            continue

        fund_id = swap.get("fund_id", "")
        token = swap.get("token", "")
        key = f"{fund_id}|{token}"

        if key not in fund_token_totals:
            fund_token_totals[key] = {"fund": swap.get("fund"), "fund_id": fund_id, "token": token, "total_usd": 0, "swap_count": 0}
        fund_token_totals[key]["total_usd"] += swap.get("usd", 0)
        fund_token_totals[key]["swap_count"] += 1

    for key, data in fund_token_totals.items():
        if data["total_usd"] >= 500000:  # $500k+ accumulation
            signals["new_whale_alert"].append({
                "fund": data["fund"],
                "fund_id": data["fund_id"],
                "token": data["token"],
                "total_usd": data["total_usd"],
                "swap_count": data["swap_count"],
                "signal_strength": "STRONG" if data["total_usd"] >= 1000000 else "MODERATE",
            })

    signals["new_whale_alert"].sort(key=lambda x: x["total_usd"], reverse=True)
    signals["new_whale_alert"] = signals["new_whale_alert"][:15]

    return {
        "signals": signals,
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "early_holder_alpha": len(signals["early_holder_alpha"]),
            "whale_convergence": len(signals["whale_convergence"]),
            "smart_money_exit": len(signals["smart_money_exit"]),
            "new_whale_alert": len(signals["new_whale_alert"]),
        },
        "profiles_loaded": len(profiles),
    }


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

                        # FILTER: Skip transactions older than 30 days
                        if days_ago > 30:
                            continue
                    except:
                        continue  # Skip unparseable timestamps

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
                    # All transactions are already filtered to 30d max
                    entity_activity[eid]["30d"][direction] += usd
                    entity_activity[eid]["30d"]["txs"].append(tx_record)

            except Exception as e:
                print(f"Error checking {entity_id}: {e}")

    # Build results
    results = []
    for entity_id, data in entity_activity.items():
        net_7d = data["7d"]["received"] - data["7d"]["sent"]
        net_30d = data["30d"]["received"] - data["30d"]["sent"]

        # Only include entities with meaningful activity
        if abs(net_30d) < 1000:
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
            "received_7d": data["7d"]["received"],
            "sent_7d": data["7d"]["sent"],
            "received_30d": data["30d"]["received"],
            "sent_30d": data["30d"]["sent"],
            "tx_count_7d": len(data["7d"]["txs"]),
            "tx_count_30d": len(data["30d"]["txs"]),
            "recent_txs": all_txs[:10],
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

            # FILTER: Skip transactions older than 30 days
            if days_ago > 30:
                continue
        except:
            continue  # Skip unparseable timestamps

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


# Cache for token prices (refresh every 5 mins)
price_cache = {"prices": {}, "last_updated": None}
price_cache_lock = threading.Lock()


def get_token_prices(symbols: list[str]) -> dict:
    """Fetch current prices from CoinGecko."""
    with price_cache_lock:
        # Return cached if fresh (< 5 mins)
        if price_cache["last_updated"] and (datetime.now() - price_cache["last_updated"]).seconds < 300:
            return price_cache["prices"]

    # Map common symbols to CoinGecko IDs
    symbol_to_id = {
        "BTC": "bitcoin", "WBTC": "bitcoin", "ETH": "ethereum", "WETH": "ethereum",
        "SOL": "solana", "BNB": "binancecoin", "AVAX": "avalanche-2", "MATIC": "matic-network",
        "ARB": "arbitrum", "OP": "optimism", "LINK": "chainlink", "UNI": "uniswap",
        "AAVE": "aave", "MKR": "maker", "SNX": "synthetix-network-token", "CRV": "curve-dao-token",
        "LDO": "lido-dao", "RPL": "rocket-pool", "DOGE": "dogecoin", "SHIB": "shiba-inu",
        "PEPE": "pepe", "FET": "fetch-ai", "RNDR": "render-token", "INJ": "injective-protocol",
        "SUI": "sui", "APT": "aptos", "SEI": "sei-network", "TIA": "celestia",
        "NEAR": "near", "ATOM": "cosmos", "DOT": "polkadot", "ADA": "cardano",
        "XRP": "ripple", "DYDX": "dydx", "GMX": "gmx", "PENDLE": "pendle",
        "ENA": "ethena", "EIGEN": "eigenlayer", "ZRO": "layerzero", "W": "wormhole",
        "JUP": "jupiter-exchange-solana", "JTO": "jito-governance-token", "PYTH": "pyth-network",
        "STX": "stacks", "RUNE": "thorchain", "OSMO": "osmosis", "FTM": "fantom",
        "BLUR": "blur", "STRK": "starknet", "ZK": "zksync", "MEME": "memecoin",
        "WLD": "worldcoin-wld", "BONK": "bonk", "WIF": "dogwifcoin",
    }

    # Get CoinGecko IDs for requested symbols
    ids_to_fetch = []
    for sym in symbols:
        sym_upper = sym.upper()
        if sym_upper in symbol_to_id:
            ids_to_fetch.append(symbol_to_id[sym_upper])

    if not ids_to_fetch:
        return {}

    try:
        ids_str = ",".join(set(ids_to_fetch))
        r = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ids_str, "vs_currencies": "usd"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            # Convert back to symbol -> price
            prices = {}
            id_to_symbol = {v: k for k, v in symbol_to_id.items()}
            for cg_id, price_data in data.items():
                if cg_id in id_to_symbol:
                    sym = id_to_symbol[cg_id]
                    prices[sym] = price_data.get("usd", 0)
                    # Also add common variants
                    if sym == "BTC":
                        prices["WBTC"] = prices["BTC"]
                    if sym == "ETH":
                        prices["WETH"] = prices["ETH"]

            with price_cache_lock:
                price_cache["prices"] = prices
                price_cache["last_updated"] = datetime.now()

            return prices
    except Exception as e:
        print(f"Error fetching prices: {e}")

    return price_cache.get("prices", {})


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

    # Get current prices from CoinGecko
    all_tokens = list(token_flows.keys())
    current_prices = get_token_prices(all_tokens)

    # Calculate P/L per token
    token_pnl = []
    total_cost_basis = 0
    total_current_value = 0
    total_realized_pnl = 0

    for token, flows in token_flows.items():
        # Skip stablecoins - no meaningful P/L
        if token in ["USDT", "USDC", "DAI", "USDE", "BUSD", "TUSD"]:
            continue

        net_amount = flows["bought_amount"] - flows["sold_amount"]

        # Skip if no net position
        if net_amount <= 0:
            # Still calculate realized P/L from closed positions
            if flows["sold_amount"] > 0 and flows["bought_amount"] > 0:
                avg_cost = flows["bought_usd"] / flows["bought_amount"]
                realized_pnl = flows["sold_usd"] - (avg_cost * flows["sold_amount"])
                if abs(realized_pnl) > 1000:
                    total_realized_pnl += realized_pnl
            continue

        # Cost basis for remaining position (pro-rata)
        if flows["bought_amount"] > 0:
            avg_cost_per_token = flows["bought_usd"] / flows["bought_amount"]
            remaining_cost_basis = avg_cost_per_token * net_amount
        else:
            remaining_cost_basis = 0

        # Current value using real prices
        current_price = current_prices.get(token, 0)
        current_value = net_amount * current_price if current_price > 0 else 0

        # Realized P/L from sales
        if flows["sold_amount"] > 0 and flows["bought_amount"] > 0:
            realized_pnl = flows["sold_usd"] - (avg_cost_per_token * flows["sold_amount"])
        else:
            realized_pnl = 0

        # Unrealized P/L
        unrealized_pnl = current_value - remaining_cost_basis if current_value > 0 else 0

        # Only include if we have meaningful data
        if remaining_cost_basis > 1000 or current_value > 1000:
            token_pnl.append({
                "token": token,
                "bought_usd": flows["bought_usd"],
                "sold_usd": flows["sold_usd"],
                "net_amount": net_amount,
                "current_price": current_price,
                "cost_basis": remaining_cost_basis,
                "current_value": current_value,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "total_pnl": realized_pnl + unrealized_pnl,
                "has_price": current_price > 0,
            })
            total_cost_basis += remaining_cost_basis
            if current_value > 0:
                total_current_value += current_value
            total_realized_pnl += realized_pnl

    token_pnl.sort(key=lambda x: abs(x["total_pnl"]), reverse=True)

    # Calculate totals (only for tokens with prices)
    tokens_with_price = [t for t in token_pnl if t["has_price"]]
    total_unrealized = sum(t["unrealized_pnl"] for t in tokens_with_price)

    return {
        "fund_id": fund_id,
        "name": fund_name,
        "token_count": len(token_pnl),
        "tokens_with_price": len(tokens_with_price),
        "portfolio_value": total_current_value,
        "total_cost_basis": total_cost_basis,
        "total_current_value": total_current_value,
        "total_realized_pnl": total_realized_pnl,
        "total_unrealized_pnl": total_unrealized,
        "total_pnl": total_realized_pnl + total_unrealized,
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


@app.get("/alpha", response_class=HTMLResponse)
def alpha_page():
    """Serve the Alpha Signals page."""
    html_path = BASE_DIR / "templates" / "alpha.html"
    return html_path.read_text()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
