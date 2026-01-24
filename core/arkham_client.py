"""Simple Arkham Intelligence API client."""

import os
import time
import httpx

BASE_URL = "https://api.arkm.com"

# ~50 verified fund entities in Arkham
FUNDS = [
    # Tier 1 - Major Crypto VCs
    "a16z",
    "paradigm-capital",
    "polychain-capital",
    "dragonfly-capital",
    "pantera-capital",
    "sequoia-capital",
    "blockchain-capital",
    "multicoin-capital",
    "placeholder-vc",
    "variant-fund",
    "haun-ventures",
    "framework-ventures",
    "1confirmation",
    "electric-capital",
    # Trading Firms & Market Makers
    "jump-trading",
    "wintermute",
    "alameda-research",
    "cumberland",
    "b2c2",
    "genesis-trading",
    "galaxy-digital",
    "dwf-labs",
    "akuna-capital",
    # Institutional
    "grayscale",
    "bitwise",
    "ark-invest",
    "digital-currency-group",
    "coinbase",
    "circle",
    "winklevoss-capital",
    # Crypto Funds
    "spartan-group",
    "animoca-brands",
    "binance-labs",
    "mirana-ventures",
    "ngc-ventures",
    "fabric-ventures",
    "delphi-digital",
    "maven-11",
    "mechanism-capital",
    "abraxas-capital-heka-funds",
    # Defunct/Historical (for reference)
    "three-arrows-capital",
    "ftx",
    "blockfi",
    "nexo",
    # Notable Individuals (optional)
    "vitalik-buterin",
    "justin-sun",
    "cz-binance",
    "brian-armstrong",
    "do-kwon",
]


def get_api_key():
    """Get API key at request time."""
    return os.environ.get("ARKHAM_API_KEY", "")


def get_headers():
    """Get headers with API key."""
    key = get_api_key()
    if not key:
        print("WARNING: ARKHAM_API_KEY not set!")
    return {"API-Key": key}


def get_entity(entity_id: str) -> dict | None:
    """Get entity info."""
    try:
        r = httpx.get(
            f"{BASE_URL}/intelligence/entity/{entity_id}",
            headers=get_headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error getting entity {entity_id}: {e}")
        return None


def get_portfolio(entity_id: str) -> dict:
    """Get portfolio holdings."""
    try:
        now_ms = int(time.time() * 1000)
        r = httpx.get(
            f"{BASE_URL}/portfolio/entity/{entity_id}",
            params={"time": now_ms},
            headers=get_headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error getting portfolio {entity_id}: {e}")
        return {}


def get_transfers(entity_id: str, limit: int = 100) -> list:
    """Get transfer history."""
    try:
        r = httpx.get(
            f"{BASE_URL}/transfers",
            params={"base": entity_id, "limit": limit},
            headers=get_headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("transfers", [])
    except Exception as e:
        print(f"Error getting transfers {entity_id}: {e}")
        return []


def get_flows(entity_id: str) -> dict:
    """Get flow data."""
    try:
        r = httpx.get(
            f"{BASE_URL}/flow/entity/{entity_id}",
            headers=get_headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Error getting flows {entity_id}: {e}")
        return {}


def list_funds() -> list[dict]:
    """Get all available funds."""
    funds = []
    for fund_id in FUNDS:
        entity = get_entity(fund_id)
        if entity and entity.get("name"):
            funds.append({
                "id": entity.get("id", fund_id),
                "name": entity.get("name", fund_id),
                "type": entity.get("type", "fund"),
            })
    return funds


def parse_portfolio(raw: dict) -> list[dict]:
    """Parse portfolio into holdings list."""
    holdings = []
    for chain, tokens in raw.items():
        if not isinstance(tokens, dict):
            continue
        for token_id, data in tokens.items():
            if not isinstance(data, dict):
                continue
            usd = data.get("usd", 0)
            if usd and usd > 0.01:
                holdings.append({
                    "token_id": token_id,
                    "name": data.get("name", "Unknown"),
                    "symbol": (data.get("symbol") or "???").upper(),
                    "chain": chain,
                    "balance": data.get("balance", 0),
                    "price": data.get("price", 0),
                    "value_usd": usd,
                })
    holdings.sort(key=lambda x: x["value_usd"], reverse=True)
    return holdings


def parse_transfers(raw: list, entity_id: str) -> list[dict]:
    """Parse transfers into activity list."""
    activity = []
    for tx in raw[:50]:  # Limit to 50
        to_entity = (tx.get("toAddress") or {}).get("arkhamEntity") or {}
        from_entity = (tx.get("fromAddress") or {}).get("arkhamEntity") or {}

        if to_entity.get("id") == entity_id:
            direction = "Received"
            counterparty = from_entity.get("name") or tx.get("fromAddress", {}).get("address", "")[:12]
        else:
            direction = "Sent"
            counterparty = to_entity.get("name") or tx.get("toAddress", {}).get("address", "")[:12]

        activity.append({
            "timestamp": tx.get("blockTimestamp", ""),
            "type": direction,
            "token": (tx.get("tokenSymbol") or "???").upper(),
            "amount": tx.get("unitValue", 0),
            "value_usd": tx.get("historicalUSD", 0),
            "counterparty": counterparty[:20] if counterparty else "Unknown",
            "chain": tx.get("chain", ""),
        })
    return activity


def calculate_cost_basis(holdings: list, transfers: list) -> dict:
    """Calculate simple cost basis from transfers."""
    # Group transfers by token
    by_token = {}
    for tx in transfers:
        symbol = (tx.get("tokenSymbol") or "").upper()
        if not symbol:
            continue
        if symbol not in by_token:
            by_token[symbol] = {"in_usd": 0, "in_amount": 0, "out_usd": 0, "out_amount": 0}

        # Determine direction
        to_entity = (tx.get("toAddress") or {}).get("arkhamEntity") or {}
        amount = tx.get("unitValue", 0) or 0
        usd = tx.get("historicalUSD", 0) or 0

        if to_entity.get("id"):  # Inflow
            by_token[symbol]["in_usd"] += usd
            by_token[symbol]["in_amount"] += amount
        else:  # Outflow
            by_token[symbol]["out_usd"] += usd
            by_token[symbol]["out_amount"] += amount

    # Calculate P/L for holdings
    result = []
    for h in holdings:
        symbol = h["symbol"]
        cb = by_token.get(symbol, {})

        in_usd = cb.get("in_usd", 0)
        in_amount = cb.get("in_amount", 0)
        avg_cost = in_usd / in_amount if in_amount > 0 else 0
        cost_basis = avg_cost * h["balance"]

        pnl = h["value_usd"] - cost_basis if cost_basis > 0 else 0
        pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

        result.append({
            **h,
            "cost_basis": cost_basis,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        })

    return result
