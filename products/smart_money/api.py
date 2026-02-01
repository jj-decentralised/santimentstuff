"""
Crypto Analytics Dashboard API.

FastAPI application serving Santiment on-chain data.
All pages are server-side rendered — no JavaScript required.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from core.cache import CacheManager
from core.santiment_client import SantimentClient
from core.santiment_cache import SantimentCache
from core.santiment_data_puller import (
    SantimentDataPuller,
    TOP_TOKENS,
    CORE_METRICS,
    TIER1_METRICS,
    TIER2_METRICS,
    ALL_PROFILE_METRICS,
)
from core.derived_metrics import (
    compute_token_derived, correlation_matrix, sector_momentum,
    mean_reversion_zscore, sortino_ratio, calmar_ratio, metcalfe_ratio,
)
from core.ssr_renderer import (
    render_briefing_page,
    render_explore_page,
    render_insights_page,
    render_valuation_page,
    render_token_profile,
    render_sync_page,
    render_compare_page,
    render_screener_page,
    render_watchlist_page,
    render_sectors_page,
    render_developers_page,
    render_market_page,
    set_ticker_data_fn,
    set_freshness_fn,
    set_theme,
    fmt_usd,
    fmt_pct,
    pct_class,
    render_glossary_page,
    render_sector_detail_page,
    render_quant_page,
    page_shell,
    _esc,
)

logger = logging.getLogger(__name__)

# Global instances
_san_client: Optional[SantimentClient] = None
_san_cache: Optional[SantimentCache] = None
_san_puller: Optional[SantimentDataPuller] = None
_san_pull_status: dict = {"status": "idle", "last_pull": None, "error": None}


async def _santiment_background_pull():
    """
    Background task: pull Santiment data in phases.

    Phase 1: Discover universe + lightweight pull (10 tokens, Tier 1, 1 year)
    Phase 2: Universe pull (ALL tokens, core metrics, 7 years)
    Phase 3: Deep pull (top 200 tokens, Tier 1+2, 7 years)
    Phase 4: Periodic refresh every 4 hours
    """
    global _san_pull_status
    if not _san_client or not _san_cache or not _san_puller:
        logger.warning("Santiment not configured, skipping background pull")
        _san_pull_status = {"status": "skipped", "reason": "SANTIMENT_API_KEY not set"}
        return

    logger.info("Santiment: Waiting 5s for app startup...")
    await asyncio.sleep(5)

    # Phase 1: Lightweight discovery + pull
    try:
        _san_pull_status = {
            "status": "phase1_discovery",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "phase": 1,
        }
        logger.info("Santiment Phase 1: Universe discovery...")
        await _san_puller.discover_universe()

        _san_pull_status["status"] = "phase1_pulling"
        _san_pull_status["universe_size"] = _san_puller.universe_size
        logger.info(f"Santiment Phase 1: Lightweight pull (10 tokens, Tier 1, 1 year). Universe: {_san_puller.universe_size}")
        phase1_stats = await _san_puller.run_lightweight_pull()

        _san_pull_status = {
            "status": "phase1_complete",
            "phase": 1,
            "last_pull": datetime.now(timezone.utc).isoformat(),
            "universe_size": _san_puller.universe_size,
            "cache_stats": _san_cache.get_pull_stats(),
            "phase1_stats": phase1_stats,
        }
        logger.info(f"Santiment Phase 1 complete: {phase1_stats.get('total_points', 0)} data points cached")

        # Pre-warm caches so first visitor gets instant response
        try:
            logger.info("Pre-warming in-memory caches...")
            _get_all_tokens()
            _get_summary_tokens()
            _build_economy_briefing()
            logger.info("Cache pre-warm complete")
        except Exception as warm_err:
            logger.warning(f"Cache pre-warm failed (non-fatal): {warm_err}")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Santiment Phase 1 failed: {e}\n{tb}")
        _san_pull_status = {
            "status": "phase1_error",
            "error": str(e),
            "traceback": tb[-500:],
            "client_stats": _san_client.stats if _san_client else None,
        }
        await asyncio.sleep(30)

    # Phase 2: Universe pull (ALL tokens, core metrics, 7 years)
    try:
        _san_pull_status["status"] = "phase2_universe"
        _san_pull_status["phase"] = 2
        _san_pull_status["universe_size"] = _san_puller.universe_size
        logger.info(f"Santiment Phase 2: Universe pull ({_san_puller.universe_size} tokens, core metrics, 7 years)...")
        universe_stats = await _san_puller.run_universe_pull()

        _san_pull_status = {
            "status": "phase2_complete",
            "phase": 2,
            "last_pull": datetime.now(timezone.utc).isoformat(),
            "universe_size": _san_puller.universe_size,
            "cache_stats": _san_cache.get_pull_stats(),
            "universe_stats": {
                "total_points": universe_stats.get("total_points", 0),
                "elapsed_minutes": universe_stats.get("elapsed_minutes", 0),
            },
        }
        logger.info(f"Santiment Phase 2 complete. {universe_stats.get('total_points', 0)} points. Cache: {_san_cache.get_pull_stats()}")

        # Warm-swap: pre-build new cache then atomically swap
        try:
            logger.info("Refreshing latest_values + warm-swapping caches after Phase 2...")
            _san_cache.refresh_all_latest_values(KEY_METRICS)
            import time as _time
            new_cache = {}
            new_all = _build_bulk_token_data(KEY_METRICS, max_tokens=500)
            new_cache["all_tokens"] = (_time.time(), new_all)
            new_cache["summary_tokens"] = (_time.time(), _build_bulk_token_data(SUMMARY_METRICS, max_tokens=200))
            _result_cache.clear()
            _result_cache.update(new_cache)
            _build_economy_briefing()
            logger.info("Phase 2 warm-swap complete")
        except Exception as warm_err:
            logger.warning(f"Phase 2 warm-swap failed (non-fatal): {warm_err}")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Santiment Phase 2 failed: {e}\n{tb}")
        _san_pull_status["status"] = "phase2_error"
        _san_pull_status["phase2_error"] = str(e)
        _san_pull_status["cache_stats"] = _san_cache.get_pull_stats()

    # Phase 3: Deep pull (top 200, Tier 1+2, 7 years)
    try:
        _san_pull_status["status"] = "phase3_deep"
        _san_pull_status["phase"] = 3
        logger.info("Santiment Phase 3: Deep pull (top 200 tokens, Tier 1+2, 7 years)...")
        deep_stats = await _san_puller.run_deep_pull(top_n=200, tiers=[1, 2])

        _san_pull_status = {
            "status": "ready",
            "phase": "complete",
            "last_pull": datetime.now(timezone.utc).isoformat(),
            "universe_size": _san_puller.universe_size,
            "cache_stats": _san_cache.get_pull_stats(),
        }
        logger.info(f"Santiment Phase 3 complete. Cache: {_san_cache.get_pull_stats()}")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Santiment Phase 3 failed: {e}\n{tb}")
        _san_pull_status["status"] = "partial"
        _san_pull_status["phase3_error"] = str(e)
        _san_pull_status["cache_stats"] = _san_cache.get_pull_stats()

    # Phase 4: Periodic refresh
    while True:
        try:
            await asyncio.sleep(4 * 3600)
            logger.info("Santiment: Running periodic refresh...")
            _san_pull_status["status"] = "refreshing"
            await _san_puller.daily_refresh()
            _san_cache.refresh_all_latest_values(KEY_METRICS)
            # Warm-swap: pre-build then atomically replace
            import time as _time
            new_cache = {}
            new_all = _build_bulk_token_data(KEY_METRICS, max_tokens=500)
            new_cache["all_tokens"] = (_time.time(), new_all)
            new_cache["summary_tokens"] = (_time.time(), _build_bulk_token_data(SUMMARY_METRICS, max_tokens=200))
            _result_cache.clear()
            _result_cache.update(new_cache)
            _build_economy_briefing()
            _san_pull_status = {
                "status": "ready",
                "last_pull": datetime.now(timezone.utc).isoformat(),
                "universe_size": _san_puller.universe_size,
                "cache_stats": _san_cache.get_pull_stats(),
            }
            logger.info("Santiment: Refresh complete")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Santiment: Refresh failed: {e}")
            _san_pull_status["error"] = str(e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _san_client, _san_cache, _san_puller

    # Initialize Santiment
    san_task = None
    san_api_key = os.environ.get("SANTIMENT_API_KEY")
    if san_api_key:
        logger.info("Santiment API key found, initializing...")
        mem_cache = CacheManager()
        try:
            _san_cache = SantimentCache()
        except Exception as cache_err:
            logger.error(f"SantimentCache init failed: {cache_err}. App will start without cached data.")
            _san_cache = None
        if _san_cache:
            _san_client = SantimentClient(api_key=san_api_key, cache=mem_cache)
            await _san_client.__aenter__()
            _san_puller = SantimentDataPuller(_san_client, _san_cache)
            san_task = asyncio.create_task(_santiment_background_pull())
        else:
            logger.warning("Running without SantimentCache — data features degraded")
    else:
        logger.warning("SANTIMENT_API_KEY not set, Santiment features disabled")

    yield

    # Cleanup
    if san_task:
        san_task.cancel()
        try:
            await san_task
        except asyncio.CancelledError:
            pass
    if _san_client:
        await _san_client.__aexit__(None, None, None)
    if _san_cache:
        _san_cache.close()


# ============================================================
# SHARED DATA HELPERS — with in-memory TTL cache
# ============================================================

KEY_METRICS = [
    "price_usd", "marketcap_usd", "volume_usd",
    "daily_active_addresses", "mvrv_usd", "nvt",
    "dev_activity", "exchange_balance", "network_growth",
    "transaction_volume",
]

SUMMARY_METRICS = [
    "price_usd", "marketcap_usd", "volume_usd",
    "daily_active_addresses", "mvrv_usd", "nvt",
]

# Bellwether tokens for economy-wide aggregate trends
BELLWETHER_SLUGS = [
    "bitcoin", "ethereum", "tether", "xrp", "binance-coin",
    "solana", "cardano", "dogecoin", "tron", "avalanche",
    "chainlink", "polkadot", "polygon", "litecoin", "uniswap",
    "stellar", "near-protocol", "internet-computer", "cosmos",
    "aave",
]

# ── Asset taxonomy ────────────────────────────────────────────
#
# Two-level classification:
#   SECTOR (what it is) → CATEGORY (what it does)
#   + THESIS (on-chain behavioral profile)
#
# Sector is structural (L1, L2, DeFi, etc.)
# Category is functional (lending, DEX, payments, etc.)
# Thesis is behavioral (accumulation, distribution, etc.)

SECTORS = {
    "l1": "Layer 1",
    "l2": "Layer 2",
    "defi": "DeFi",
    "stablecoin": "Stablecoin",
    "exchange": "Exchange Token",
    "meme": "Meme",
    "ai": "AI & Data",
    "gaming": "Gaming & Metaverse",
    "infrastructure": "Infrastructure",
    "privacy": "Privacy",
    "storage": "Storage",
    "oracle": "Oracle",
    "social": "Social & Identity",
    "rwa": "Real World Assets",
    "other": "Other",
}

CATEGORIES = {
    # L1 subcategories
    "smart_contract_platform": "Smart Contract Platform",
    "payments": "Payments & Currency",
    "pos_chain": "PoS Chain",
    "pow_chain": "PoW Chain",
    # L2
    "rollup": "Rollup",
    "sidechain": "Sidechain",
    "state_channel": "State Channel",
    # DeFi
    "dex": "DEX",
    "lending": "Lending & Borrowing",
    "yield": "Yield & Staking",
    "derivatives": "Derivatives",
    "bridge": "Bridge",
    "liquid_staking": "Liquid Staking",
    "stablecoin_algo": "Algorithmic Stablecoin",
    "stablecoin_fiat": "Fiat-Backed Stablecoin",
    # Infrastructure
    "interop": "Interoperability",
    "compute": "Compute & Cloud",
    "data_index": "Data & Indexing",
    "identity": "Identity & DNS",
    # Other
    "governance": "Governance",
    "nft_platform": "NFT Platform",
    "launchpad": "Launchpad",
    "cex_token": "CEX Token",
    "dex_token": "DEX Token",
    "meme_dog": "Dog Meme",
    "meme_other": "Other Meme",
    "ai_agent": "AI Agent",
    "ai_compute": "AI Compute",
    "depin": "DePIN",
    "gaming_token": "Gaming Token",
    "metaverse": "Metaverse",
    "privacy_coin": "Privacy Coin",
    "storage_token": "Decentralized Storage",
    "oracle_token": "Oracle Network",
    "rwa_token": "RWA Tokenization",
    "social_token": "Social Token",
    "other": "Uncategorized",
}

# Known slug → (sector, category) mappings for top projects
# This covers ~200 important tokens; everything else is classified by heuristics
SLUG_TAXONOMY = {
    # ── Layer 1 ──
    "bitcoin": ("l1", "pow_chain"),
    "ethereum": ("l1", "smart_contract_platform"),
    "solana": ("l1", "smart_contract_platform"),
    "cardano": ("l1", "pos_chain"),
    "avalanche": ("l1", "smart_contract_platform"),
    "polkadot": ("l1", "interop"),
    "cosmos": ("l1", "interop"),
    "near-protocol": ("l1", "smart_contract_platform"),
    "internet-computer": ("l1", "compute"),
    "algorand": ("l1", "smart_contract_platform"),
    "tezos": ("l1", "smart_contract_platform"),
    "eos": ("l1", "smart_contract_platform"),
    "flow": ("l1", "smart_contract_platform"),
    "hedera": ("l1", "smart_contract_platform"),
    "sui": ("l1", "smart_contract_platform"),
    "aptos": ("l1", "smart_contract_platform"),
    "sei": ("l1", "smart_contract_platform"),
    "tron": ("l1", "smart_contract_platform"),
    "fantom": ("l1", "smart_contract_platform"),
    "harmony": ("l1", "smart_contract_platform"),
    "zilliqa": ("l1", "smart_contract_platform"),
    "elrond": ("l1", "smart_contract_platform"),
    "celo": ("l1", "payments"),
    "kaspa": ("l1", "pow_chain"),
    "ton": ("l1", "smart_contract_platform"),
    "injective": ("l1", "smart_contract_platform"),
    "celestia": ("l1", "smart_contract_platform"),
    "monad": ("l1", "smart_contract_platform"),
    "berachain": ("l1", "smart_contract_platform"),

    # ── Layer 2 ──
    "polygon": ("l2", "sidechain"),
    "arbitrum": ("l2", "rollup"),
    "optimism": ("l2", "rollup"),
    "starknet": ("l2", "rollup"),
    "zksync": ("l2", "rollup"),
    "base": ("l2", "rollup"),
    "immutable-x": ("l2", "rollup"),
    "mantle": ("l2", "rollup"),
    "stacks": ("l2", "sidechain"),
    "metis": ("l2", "rollup"),
    "loopring": ("l2", "rollup"),
    "skale": ("l2", "sidechain"),
    "boba-network": ("l2", "rollup"),
    "mina-protocol": ("l2", "rollup"),
    "scroll": ("l2", "rollup"),
    "linea": ("l2", "rollup"),
    "blast": ("l2", "rollup"),

    # ── Payments ──
    "xrp": ("l1", "payments"),
    "litecoin": ("l1", "payments"),
    "bitcoin-cash": ("l1", "payments"),
    "stellar": ("l1", "payments"),
    "nano": ("l1", "payments"),
    "dash": ("l1", "payments"),

    # ── DeFi: DEX ──
    "uniswap": ("defi", "dex"),
    "sushiswap": ("defi", "dex"),
    "curve-dao-token": ("defi", "dex"),
    "pancakeswap": ("defi", "dex"),
    "1inch": ("defi", "dex"),
    "dydx": ("defi", "derivatives"),
    "balancer": ("defi", "dex"),
    "raydium": ("defi", "dex"),
    "jupiter": ("defi", "dex"),
    "orca": ("defi", "dex"),
    "osmosis": ("defi", "dex"),
    "camelot-token": ("defi", "dex"),
    "trader-joe": ("defi", "dex"),
    "aerodrome-finance": ("defi", "dex"),
    "velodrome-finance": ("defi", "dex"),

    # ── DeFi: Lending ──
    "aave": ("defi", "lending"),
    "compound": ("defi", "lending"),
    "maker": ("defi", "lending"),
    "venus": ("defi", "lending"),
    "morpho": ("defi", "lending"),
    "radiant-capital": ("defi", "lending"),
    "benqi": ("defi", "lending"),

    # ── DeFi: Yield / Liquid Staking ──
    "lido-dao": ("defi", "liquid_staking"),
    "rocket-pool": ("defi", "liquid_staking"),
    "frax-share": ("defi", "yield"),
    "convex-finance": ("defi", "yield"),
    "yearn-finance": ("defi", "yield"),
    "pendle": ("defi", "yield"),
    "eigenlayer": ("defi", "yield"),
    "ethena": ("defi", "yield"),
    "jito": ("defi", "liquid_staking"),
    "marinade-finance": ("defi", "liquid_staking"),

    # ── DeFi: Derivatives ──
    "synthetix-network-token": ("defi", "derivatives"),
    "gmx": ("defi", "derivatives"),
    "perpetual-protocol": ("defi", "derivatives"),
    "gains-network": ("defi", "derivatives"),
    "ribbon-finance": ("defi", "derivatives"),
    "drift-protocol": ("defi", "derivatives"),
    "hyperliquid": ("defi", "derivatives"),

    # ── DeFi: Bridges ──
    "wormhole": ("defi", "bridge"),
    "layerzero": ("defi", "bridge"),
    "stargate-finance": ("defi", "bridge"),
    "across-protocol": ("defi", "bridge"),
    "synapse-2": ("defi", "bridge"),
    "axelar": ("infrastructure", "interop"),

    # ── Stablecoins ──
    "tether": ("stablecoin", "stablecoin_fiat"),
    "usd-coin": ("stablecoin", "stablecoin_fiat"),
    "dai": ("stablecoin", "stablecoin_algo"),
    "binance-usd": ("stablecoin", "stablecoin_fiat"),
    "trueusd": ("stablecoin", "stablecoin_fiat"),
    "first-digital-usd": ("stablecoin", "stablecoin_fiat"),
    "frax": ("stablecoin", "stablecoin_algo"),
    "ethena-usde": ("stablecoin", "stablecoin_algo"),
    "paypal-usd": ("stablecoin", "stablecoin_fiat"),

    # ── Exchange Tokens ──
    "binance-coin": ("exchange", "cex_token"),
    "crypto-com-chain": ("exchange", "cex_token"),
    "okb": ("exchange", "cex_token"),
    "kucoin-shares": ("exchange", "cex_token"),
    "gate-token": ("exchange", "cex_token"),
    "bitget-token": ("exchange", "cex_token"),
    "huobi-token": ("exchange", "cex_token"),
    "leo": ("exchange", "cex_token"),
    "mx-token": ("exchange", "cex_token"),

    # ── Meme ──
    "dogecoin": ("meme", "meme_dog"),
    "shiba-inu": ("meme", "meme_dog"),
    "pepe": ("meme", "meme_other"),
    "bonk": ("meme", "meme_dog"),
    "floki": ("meme", "meme_dog"),
    "memecoin": ("meme", "meme_other"),
    "dogwifhat": ("meme", "meme_dog"),
    "brett": ("meme", "meme_other"),
    "cat-in-a-dogs-world": ("meme", "meme_other"),
    "book-of-meme": ("meme", "meme_other"),
    "turbo": ("meme", "meme_other"),
    "wojak": ("meme", "meme_other"),
    "neiro": ("meme", "meme_dog"),
    "mog-coin": ("meme", "meme_other"),
    "popcat": ("meme", "meme_other"),

    # ── AI & Data ──
    "fetch": ("ai", "ai_agent"),
    "singularitynet": ("ai", "ai_agent"),
    "ocean-protocol": ("ai", "ai_compute"),
    "render-token": ("ai", "ai_compute"),
    "bittensor": ("ai", "ai_compute"),
    "worldcoin": ("ai", "identity"),
    "arkham": ("ai", "data_index"),
    "numeraire": ("ai", "ai_compute"),
    "akash-network": ("ai", "ai_compute"),
    "artificial-superintelligence-alliance": ("ai", "ai_agent"),
    "io-net": ("ai", "ai_compute"),
    "virtual-protocol": ("ai", "ai_agent"),
    "ai16z": ("ai", "ai_agent"),
    "grass": ("ai", "data_index"),
    "golem": ("ai", "ai_compute"),

    # ── Gaming & Metaverse ──
    "the-sandbox": ("gaming", "metaverse"),
    "decentraland": ("gaming", "metaverse"),
    "axie-infinity": ("gaming", "gaming_token"),
    "gala": ("gaming", "gaming_token"),
    "illuvium": ("gaming", "gaming_token"),
    "beam": ("gaming", "gaming_token"),
    "ronin": ("gaming", "gaming_token"),
    "gods-unchained": ("gaming", "gaming_token"),
    "ultra": ("gaming", "gaming_token"),
    "enjin-coin": ("gaming", "nft_platform"),
    "pixels": ("gaming", "gaming_token"),
    "xai": ("gaming", "gaming_token"),

    # ── Infrastructure ──
    "chainlink": ("oracle", "oracle_token"),
    "pyth-network": ("oracle", "oracle_token"),
    "band-protocol": ("oracle", "oracle_token"),
    "api3": ("oracle", "oracle_token"),
    "uma": ("oracle", "oracle_token"),
    "the-graph": ("infrastructure", "data_index"),
    "arweave": ("storage", "storage_token"),
    "filecoin": ("storage", "storage_token"),
    "theta-token": ("infrastructure", "compute"),
    "quant": ("infrastructure", "interop"),
    "vechain": ("infrastructure", "data_index"),
    "iota": ("infrastructure", "data_index"),
    "helium": ("infrastructure", "depin"),

    # ── Privacy ──
    "monero": ("privacy", "privacy_coin"),
    "zcash": ("privacy", "privacy_coin"),
    "secret": ("privacy", "privacy_coin"),
    "oasis-network": ("privacy", "privacy_coin"),

    # ── Social & Identity ──
    "ens": ("social", "identity"),
    "lens-protocol": ("social", "social_token"),
    "galxe": ("social", "identity"),
    "mask-network": ("social", "social_token"),
    "cyberconnect": ("social", "social_token"),

    # ── RWA ──
    "ondo-finance": ("rwa", "rwa_token"),
    "centrifuge": ("rwa", "rwa_token"),
    "polymesh": ("rwa", "rwa_token"),
    "maple-finance": ("rwa", "rwa_token"),
    "goldfinch": ("rwa", "rwa_token"),
    "mantra": ("rwa", "rwa_token"),
    "tokenfi": ("rwa", "rwa_token"),
}

THESIS_DEFS = {
    "smart_money": "Smart Money Accumulating",
    "builder_momentum": "Builder Momentum",
    "deep_value": "Deep Value",
    "distribution_warning": "Distribution Warning",
    "hodler": "HODLer Coins",
    "high_utility": "High Utility",
    "speculative": "Speculative",
    "uncategorized": "Uncategorized",
}

# Scatter plot view definitions: (id, title, x_metric, y_metric, x_label, y_label, log_x, log_y)
SCATTER_VIEWS = [
    ("mvrv_nvt", "Value Map: MVRV vs NVT", "mvrv_usd", "nvt", "MVRV Ratio", "NVT Ratio", False, True),
    ("daa_mcap", "Usage vs Valuation: DAA vs Market Cap", "daily_active_addresses", "marketcap_usd", "Active Addresses", "Market Cap (USD)", True, True),
    ("exch_price", "Smart Money: Exchange Bal Change vs Price Change", "exchange_balance_change", "price_usd_change", "Exchange Balance Change %", "Price Change %", False, False),
    ("dev_growth", "Builder Momentum: Dev Activity vs Network Growth", "dev_activity", "network_growth", "Dev Activity", "Network Growth", True, True),
    ("vol_mcap", "Speculation: Volume/MCap Ratio vs Active Addresses", "vol_mcap_ratio", "daily_active_addresses", "Volume / Market Cap", "Active Addresses", True, True),
]

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
_CACHE_TTL = 14400  # seconds — 4 hours, aligned with data refresh cycle

# In-memory result cache: {key: (timestamp, value)}
_result_cache: dict = {}


def _cached(key: str, builder, ttl: int = _CACHE_TTL):
    """Return cached result or compute and cache it."""
    import time as _time
    now = _time.time()
    entry = _result_cache.get(key)
    if entry and (now - entry[0]) < ttl:
        return entry[1]
    result = builder()
    _result_cache[key] = (now, result)
    return result


# ── Bulk token data ──────────────────────────────────────────

def _build_bulk_token_data(metrics_list: list[str], max_tokens: int = 0) -> list[dict]:
    """One SQL query per metric instead of per token×metric.
    max_tokens: if > 0, only return the top N tokens by market cap (speed optimization).
    """
    if not _san_cache:
        return []
    all_projects = _san_cache.get_all_projects()
    slug_map = {}
    for project in all_projects:
        slug = project.get("slug")
        if not slug:
            continue
        name = project.get("name", slug)
        infra = project.get("infrastructure", "")
        sector, category = _classify_sector_category(slug, infra, name)
        slug_map[slug] = {
            "slug": slug,
            "name": name,
            "ticker": project.get("ticker", ""),
            "infrastructure": infra,
            "sector": sector,
            "category": category,
        }
    for metric in metrics_list:
        bulk = _san_cache.get_latest_values(metric)
        for slug, vals in bulk.items():
            if slug not in slug_map:
                continue
            latest = vals.get("latest")
            prev = vals.get("prev")
            slug_map[slug][metric] = latest
            if latest is not None and prev is not None and prev != 0:
                slug_map[slug][f"{metric}_change"] = round((latest - prev) / prev * 100, 2)
            else:
                slug_map[slug][f"{metric}_change"] = 0 if latest is not None else None
    tokens = [t for t in slug_map.values() if t.get("price_usd") is not None]
    tokens.sort(key=lambda x: x.get("marketcap_usd") or 0, reverse=True)
    if max_tokens > 0:
        tokens = tokens[:max_tokens]
    return tokens


def _get_all_tokens() -> list[dict]:
    """Top 500 tokens by market cap — covers 99.9% of market value."""
    return _cached("all_tokens", lambda: _build_bulk_token_data(KEY_METRICS, max_tokens=500))


def _get_summary_tokens() -> list[dict]:
    """Lightweight summary: top 200 tokens, fewer metrics."""
    return _cached("summary_tokens", lambda: _build_bulk_token_data(SUMMARY_METRICS, max_tokens=200))


# Ticker strip data — top tokens for the price bar across all pages
_TICKER_SLUGS = ["bitcoin", "ethereum", "solana", "xrp", "binance-coin", "cardano", "dogecoin", "avalanche"]

def _get_ticker_data() -> list[dict]:
    """Return compact price data for the header ticker strip."""
    def _build():
        tokens = _get_all_tokens()
        slug_map = {t["slug"]: t for t in tokens}
        result = []
        for slug in _TICKER_SLUGS:
            t = slug_map.get(slug)
            if t:
                result.append({
                    "slug": slug,
                    "ticker": t.get("ticker", ""),
                    "price": t.get("price_usd"),
                    "change": t.get("price_usd_change"),
                })
        return result
    return _cached("ticker_data", _build)


# ── Economy-level aggregates ─────────────────────────────────

def _build_economy_briefing() -> dict:
    """
    Core economy briefing — answers:
      1. What regime are we in? (MVRV distribution, breadth)
      2. Where is capital flowing? (exchange balance, volume concentration)
      3. How healthy are networks? (aggregate DAA, dev activity, growth)
      4. What moved meaningfully? (on-chain signals, not just price noise)
      5. What's the valuation landscape? (zone distribution)
    """
    def _compute():
        tokens = _get_all_tokens()
        if not tokens:
            return {}

        # ── 1. Market regime ──
        total_mcap = sum(t.get("marketcap_usd") or 0 for t in tokens)
        total_vol = sum(t.get("volume_usd") or 0 for t in tokens)
        mvrv_vals = [t["mvrv_usd"] for t in tokens if t.get("mvrv_usd") is not None]
        avg_mvrv = sum(mvrv_vals) / len(mvrv_vals) if mvrv_vals else None
        pos = sum(1 for t in tokens if (t.get("price_usd_change") or 0) > 0)
        neg = sum(1 for t in tokens if (t.get("price_usd_change") or 0) < 0)
        flat = len(tokens) - pos - neg

        # ── 1b. Sector distribution ──
        sector_data = {}
        for t in tokens:
            sec = t.get("sector", "other")
            if sec not in sector_data:
                sector_data[sec] = {"count": 0, "mcap": 0, "vol": 0, "up": 0, "down": 0, "pct_sum": 0}
            sector_data[sec]["count"] += 1
            sector_data[sec]["mcap"] += t.get("marketcap_usd") or 0
            sector_data[sec]["vol"] += t.get("volume_usd") or 0
            chg = t.get("price_usd_change") or 0
            sector_data[sec]["pct_sum"] += chg
            if chg > 0:
                sector_data[sec]["up"] += 1
            elif chg < 0:
                sector_data[sec]["down"] += 1

        # ── 2. MVRV zone distribution ──
        zones = {"deep_value": 0, "undervalued": 0, "fair": 0, "elevated": 0, "overvalued": 0, "euphoria": 0}
        for v in mvrv_vals:
            if v < 0.7:
                zones["deep_value"] += 1
            elif v < 1.0:
                zones["undervalued"] += 1
            elif v < 1.5:
                zones["fair"] += 1
            elif v < 2.5:
                zones["elevated"] += 1
            elif v < 3.5:
                zones["overvalued"] += 1
            else:
                zones["euphoria"] += 1

        # ── 3. Capital flows — volume concentration + exchange balance ──
        top10_vol = sum(t.get("volume_usd") or 0 for t in tokens[:10])
        vol_concentration = (top10_vol / total_vol * 100) if total_vol > 0 else 0

        # Exchange balance changes (accumulation vs distribution signal)
        exch_tokens = [t for t in tokens if t.get("exchange_balance") is not None and t.get("exchange_balance_change") is not None]
        accum_count = sum(1 for t in exch_tokens if (t.get("exchange_balance_change") or 0) < -1)
        distrib_count = sum(1 for t in exch_tokens if (t.get("exchange_balance_change") or 0) > 1)

        # ── 4. Network health aggregates ──
        total_daa = sum(t.get("daily_active_addresses") or 0 for t in tokens)
        daa_with_change = [t for t in tokens if t.get("daily_active_addresses_change") is not None]
        avg_daa_change = (sum(t["daily_active_addresses_change"] for t in daa_with_change) / len(daa_with_change)) if daa_with_change else None

        dev_tokens = [t for t in tokens if t.get("dev_activity") is not None]
        total_dev = sum(t.get("dev_activity") or 0 for t in dev_tokens)
        dev_with_change = [t for t in dev_tokens if t.get("dev_activity_change") is not None]
        avg_dev_change = (sum(t["dev_activity_change"] for t in dev_with_change) / len(dev_with_change)) if dev_with_change else None

        growth_tokens = [t for t in tokens if t.get("network_growth") is not None]
        total_growth = sum(t.get("network_growth") or 0 for t in growth_tokens)

        # ── 5. Notable on-chain moves (signals, not just price) ──
        signals = []

        # Biggest DAA changes (network activity spikes)
        daa_movers = sorted(
            [t for t in tokens if t.get("daily_active_addresses_change") is not None and abs(t.get("daily_active_addresses_change") or 0) > 10],
            key=lambda t: abs(t.get("daily_active_addresses_change") or 0), reverse=True,
        )[:5]
        for t in daa_movers:
            ch = t["daily_active_addresses_change"]
            signals.append({
                "slug": t["slug"], "name": t["name"], "ticker": t["ticker"],
                "signal": "daa_spike" if ch > 0 else "daa_drop",
                "metric": "Active Addresses",
                "change": ch,
            })

        # Exchange balance shifts (accumulation/distribution)
        exch_movers = sorted(
            [t for t in exch_tokens if abs(t.get("exchange_balance_change") or 0) > 3],
            key=lambda t: abs(t.get("exchange_balance_change") or 0), reverse=True,
        )[:5]
        for t in exch_movers:
            ch = t["exchange_balance_change"]
            signals.append({
                "slug": t["slug"], "name": t["name"], "ticker": t["ticker"],
                "signal": "distribution" if ch > 0 else "accumulation",
                "metric": "Exchange Balance",
                "change": ch,
            })

        # Dev activity changes
        dev_movers = sorted(
            [t for t in dev_tokens if t.get("dev_activity_change") is not None and abs(t.get("dev_activity_change") or 0) > 15],
            key=lambda t: abs(t.get("dev_activity_change") or 0), reverse=True,
        )[:5]
        for t in dev_movers:
            ch = t["dev_activity_change"]
            signals.append({
                "slug": t["slug"], "name": t["name"], "ticker": t["ticker"],
                "signal": "dev_surge" if ch > 0 else "dev_decline",
                "metric": "Dev Activity",
                "change": ch,
            })

        # ── 6. Aggregate trend lines (for charts) ──
        trends = {}
        if _san_cache:
            for metric_key, label in [
                ("daily_active_addresses", "daa"),
                ("dev_activity", "dev"),
                ("network_growth", "growth"),
                ("volume_usd", "volume"),
            ]:
                data = _san_cache.get_aggregate_timeseries(metric_key, BELLWETHER_SLUGS, days=90)
                if data and len(data) > 5:
                    trends[label] = data

            # BTC price as market proxy
            btc_data = _san_cache.get_timeseries("price_usd", "bitcoin")
            if btc_data and len(btc_data) > 90:
                trends["btc_price"] = btc_data[-90:]
            elif btc_data:
                trends["btc_price"] = btc_data

            # BTC mcap trend
            btc_mcap = _san_cache.get_timeseries("marketcap_usd", "bitcoin")
            if btc_mcap and len(btc_mcap) > 90:
                trends["btc_mcap"] = btc_mcap[-90:]
            elif btc_mcap:
                trends["btc_mcap"] = btc_mcap

        # ── 7. Gainers / Losers ──
        valid = [t for t in tokens if t.get("price_usd_change") is not None and abs(t.get("price_usd_change", 0)) < 500]
        valid.sort(key=lambda x: x.get("price_usd_change", 0), reverse=True)
        gainers = valid[:10]
        losers = list(reversed(valid[-10:]))

        # ── 8. Top by various metrics ──
        top_volume = tokens[:10]
        top_daa = sorted([t for t in tokens if t.get("daily_active_addresses")],
                         key=lambda t: t.get("daily_active_addresses") or 0, reverse=True)[:10]
        top_dev = sorted([t for t in tokens if t.get("dev_activity")],
                         key=lambda t: t.get("dev_activity") or 0, reverse=True)[:10]

        return {
            # Regime
            "total_tokens": len(tokens),
            "total_mcap": total_mcap,
            "total_vol": total_vol,
            "avg_mvrv": avg_mvrv,
            "breadth": {"up": pos, "down": neg, "flat": flat},
            "mvrv_zones": zones,
            "mvrv_total": len(mvrv_vals),
            "sector_data": sector_data,

            # Capital flows
            "vol_concentration_top10": vol_concentration,
            "accumulating": accum_count,
            "distributing": distrib_count,

            # Network health
            "total_daa": total_daa,
            "avg_daa_change": avg_daa_change,
            "total_dev": total_dev,
            "avg_dev_change": avg_dev_change,
            "total_growth": total_growth,

            # Signals
            "signals": signals[:15],

            # Trends (for charts)
            "trends": trends,

            # Movers
            "gainers": gainers,
            "losers": losers,

            # Top lists
            "top_volume": top_volume,
            "top_daa": top_daa,
            "top_dev": top_dev,

            # Full token list for heatmap/dominance
            "all_tokens": tokens,
        }

    return _cached("economy_briefing", _compute)


# ── Asset classification ──────────────────────────────────────

def _classify_sector_category(slug: str, infra: str = "", name: str = "") -> tuple:
    """Classify a token into (sector, category) using known mappings + heuristics."""
    # 1. Known slug mapping
    if slug in SLUG_TAXONOMY:
        return SLUG_TAXONOMY[slug]

    # 2. Name/slug heuristics
    slug_lower = slug.lower()
    name_lower = (name or "").lower()

    # Stablecoin detection
    for kw in ("usd", "usdt", "usdc", "dai", "busd", "tusd", "stable"):
        if kw in slug_lower and ("coin" in slug_lower or "dollar" in slug_lower or "usd" in slug_lower):
            return ("stablecoin", "stablecoin_fiat")

    # Meme detection
    for kw in ("doge", "shib", "pepe", "bonk", "floki", "meme", "inu", "wojak", "chad", "frog"):
        if kw in slug_lower or kw in name_lower:
            if "dog" in slug_lower or "inu" in slug_lower or "doge" in slug_lower or "shib" in slug_lower:
                return ("meme", "meme_dog")
            return ("meme", "meme_other")

    # DeFi detection
    for kw in ("swap", "finance", "protocol", "lend", "yield", "stake", "vault", "pool"):
        if kw in slug_lower or kw in name_lower:
            if "swap" in slug_lower or "dex" in slug_lower:
                return ("defi", "dex")
            if "lend" in slug_lower or "borrow" in slug_lower:
                return ("defi", "lending")
            if "stake" in slug_lower or "liquid" in slug_lower:
                return ("defi", "liquid_staking")
            return ("defi", "yield")

    # Gaming detection
    for kw in ("game", "play", "metaverse", "nft", "pixel", "world"):
        if kw in slug_lower or kw in name_lower:
            if "meta" in slug_lower or "land" in slug_lower or "world" in slug_lower:
                return ("gaming", "metaverse")
            return ("gaming", "gaming_token")

    # AI detection
    for kw in ("ai", "neural", "intelligence", "machine", "data", "compute"):
        if kw in slug_lower or kw in name_lower:
            return ("ai", "ai_compute")

    # Infrastructure by chain
    infra_lower = (infra or "").lower()
    if infra_lower in ("ethereum", "eth"):
        return ("defi", "other")  # Default ERC-20 tokens to DeFi/Other
    if infra_lower in ("binance smart chain", "bsc"):
        return ("defi", "other")
    if infra_lower in ("solana",):
        return ("defi", "other")

    # L2 detection
    for kw in ("layer-2", "l2", "rollup", "zk"):
        if kw in slug_lower:
            return ("l2", "rollup")

    # Privacy detection
    for kw in ("privacy", "private", "anonymous", "zero-knowledge"):
        if kw in slug_lower or kw in name_lower:
            return ("privacy", "privacy_coin")

    # Storage detection
    for kw in ("storage", "file", "store"):
        if kw in slug_lower or kw in name_lower:
            return ("storage", "storage_token")

    return ("other", "other")


def _classify_thesis(t: dict) -> str:
    """Classify a token into a thesis category based on on-chain signals."""
    mvrv = t.get("mvrv_usd")
    exch_ch = t.get("exchange_balance_change") or 0
    dev = t.get("dev_activity") or 0
    dev_ch = t.get("dev_activity_change") or 0
    daa = t.get("daily_active_addresses") or 0
    daa_ch = t.get("daily_active_addresses_change") or 0
    growth_ch = t.get("network_growth_change") or 0
    price_ch = t.get("price_usd_change") or 0
    vol = t.get("volume_usd") or 0
    mcap = t.get("marketcap_usd") or 0

    vol_mcap = vol / mcap if mcap > 0 else 0

    # Smart Money Accumulating: exchange balance dropping, price flat/down
    if exch_ch < -2 and price_ch < 5:
        return "smart_money"

    # Distribution Warning: exchange balance rising + high MVRV
    if exch_ch > 2 and mvrv is not None and mvrv > 1.8:
        return "distribution_warning"

    # Builder Momentum: dev activity rising + network growth positive
    if dev > 5 and (dev_ch > 10 or growth_ch > 10):
        return "builder_momentum"

    # Deep Value: MVRV below 0.7 + some DAA
    if mvrv is not None and mvrv < 0.7 and daa > 50:
        return "deep_value"

    # High Utility: high DAA relative to market cap (top usage tokens)
    if daa > 1000 and mcap > 0 and (daa / (mcap / 1e6)) > 0.5:
        return "high_utility"

    # Speculative: high volume/mcap + low active addresses
    if vol_mcap > 0.3 and daa < 200:
        return "speculative"

    # HODLer Coins: low volume/mcap, moderate MVRV
    if vol_mcap < 0.05 and mvrv is not None and 0.8 < mvrv < 2.0:
        return "hodler"

    return "uncategorized"


def _build_insights_data(view_id: str = "mvrv_nvt") -> dict:
    """Build scatter plot data + thesis categories for the insights page."""
    def _compute():
        tokens = _get_all_tokens()
        if not tokens:
            return {"points": [], "thesis_counts": {}, "thesis_tokens": {}}

        # Classify all tokens
        for t in tokens:
            t["thesis"] = _classify_thesis(t)
            mcap = t.get("marketcap_usd") or 0
            vol = t.get("volume_usd") or 0
            t["vol_mcap_ratio"] = vol / mcap if mcap > 0 else 0

        # Thesis counts
        thesis_counts = {}
        thesis_tokens = {}
        # Sector counts
        sector_counts = {}
        category_counts = {}
        for t in tokens:
            th = t["thesis"]
            thesis_counts[th] = thesis_counts.get(th, 0) + 1
            if th not in thesis_tokens:
                thesis_tokens[th] = []
            if len(thesis_tokens[th]) < 10:  # top 10 per category
                thesis_tokens[th].append({
                    "slug": t["slug"], "name": t["name"], "ticker": t["ticker"],
                    "price_usd": t.get("price_usd"),
                    "marketcap_usd": t.get("marketcap_usd"),
                    "mvrv_usd": t.get("mvrv_usd"),
                    "price_usd_change": t.get("price_usd_change"),
                    "sector": t.get("sector", "other"),
                    "category": t.get("category", "other"),
                })
            # Sector/category counts
            sec = t.get("sector", "other")
            cat = t.get("category", "other")
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Build scatter points (only tokens with the needed metrics)
        # Find the view definition
        view = None
        for v in SCATTER_VIEWS:
            if v[0] == view_id:
                view = v
                break
        if not view:
            view = SCATTER_VIEWS[0]

        _, _, x_metric, y_metric, _, _, _, _ = view

        points = []
        for t in tokens:
            xv = t.get(x_metric)
            yv = t.get(y_metric)
            if xv is None or yv is None:
                continue
            points.append({
                "x": xv, "y": yv,
                "slug": t["slug"], "name": t["name"], "ticker": t["ticker"],
                "thesis": t["thesis"],
                "sector": t.get("sector", "other"),
                "category": t.get("category", "other"),
                "marketcap_usd": t.get("marketcap_usd") or 0,
            })

        return {
            "points": points,
            "thesis_counts": thesis_counts,
            "thesis_tokens": thesis_tokens,
            "sector_counts": sector_counts,
            "category_counts": category_counts,
            "total_tokens": len(tokens),
        }

    return _cached(f"insights_{view_id}", _compute)


# ── Page-specific data builders ──────────────────────────────

def _build_token_list(page: int = 1, per_page: int = DEFAULT_PAGE_SIZE, sector: str = "all", category: str = "all", search: str = "", sort_by: str = "marketcap_usd", order: str = "desc"):
    tokens = list(_get_all_tokens())  # copy so we don't mutate cache
    if search:
        q = search.lower().strip()
        tokens = [t for t in tokens if q in t.get("name", "").lower() or q in t.get("slug", "").lower() or q in t.get("ticker", "").lower()]
    if sector != "all":
        tokens = [t for t in tokens if t.get("sector") == sector]
    if category != "all":
        tokens = [t for t in tokens if t.get("category") == category]
    # Sort
    valid_sorts = {"marketcap_usd", "price_usd", "price_usd_change", "volume_usd", "mvrv_usd", "daily_active_addresses", "dev_activity", "name"}
    if sort_by in valid_sorts:
        if sort_by == "name":
            tokens.sort(key=lambda x: (x.get("name") or "").lower(), reverse=(order == "desc"))
        else:
            tokens.sort(key=lambda x: x.get(sort_by) or 0, reverse=(order == "desc"))
    total = len(tokens)
    start = (page - 1) * per_page
    end = start + per_page
    page_tokens = tokens[start:end]
    # Sparklines — single batch query instead of N serial queries
    slugs = [t["slug"] for t in page_tokens]
    sparkline_data = _san_cache.get_timeseries_multi_slugs("price_usd", slugs, limit_per_slug=7)
    for t in page_tokens:
        t["sparkline_7d"] = sparkline_data.get(t["slug"], [])
    return page_tokens, total


def _build_all_tokens_for_valuation():
    tokens = _get_all_tokens()
    return [t for t in tokens if t.get("mvrv_usd") is not None and t.get("price_usd") is not None]


def _build_profile_metrics(slug: str, limit_days: int = 365):
    """Build full metrics for a token profile — cached per slug for 15 min."""
    cache_key = f"profile_{slug}_{limit_days}"
    return _cached(cache_key, lambda: _build_profile_metrics_uncached(slug, limit_days))


def _build_profile_metrics_uncached(slug: str, limit_days: int = 365):
    # Single batch query for all metrics — limit_days reduces 142K→21K rows
    batch = _san_cache.get_timeseries_batch(ALL_PROFILE_METRICS, slug, limit_days=limit_days)
    metrics_data = {}
    for metric, data in batch.items():
        if data:
            values = [d["value"] for d in data if d.get("value") is not None]
            metrics_data[metric] = {
                "data": data,
                "count": len(data),
                "latest": data[-1]["value"] if data else None,
                "latest_date": data[-1]["datetime"] if data else None,
                "min_365d": min(values[-365:]) if len(values) >= 30 else (min(values) if values else None),
                "max_365d": max(values[-365:]) if len(values) >= 30 else (max(values) if values else None),
                "avg_30d": round(sum(values[-30:]) / len(values[-30:]), 4) if len(values) >= 30 else None,
            }

    # ── Compute derived / precalculated metrics ──
    def _vals(key):
        m = metrics_data.get(key, {})
        data = m.get("data", [])
        return [d["value"] for d in data if d.get("value") is not None]

    def _latest(key):
        m = metrics_data.get(key, {})
        return m.get("latest")

    price_vals = _vals("price_usd")
    # Get BTC prices for beta calculation
    btc_prices = []
    if _san_cache:
        btc_data = _san_cache.get_timeseries("price_usd", "bitcoin")
        btc_prices = [d["value"] for d in btc_data if d.get("value") is not None]

    # Compute change metrics for composites
    def _pct_change(vals, days):
        if len(vals) < days + 1:
            return None
        old = vals[-(days + 1)]
        if old and old != 0:
            return round((vals[-1] - old) / old * 100, 2)
        return None

    price_change_7d = _pct_change(price_vals, 7)
    price_change_30d = _pct_change(price_vals, 30)
    vol_vals = _vals("volume_usd")
    volume_change = _pct_change(vol_vals, 1) if vol_vals else None

    mcap = _latest("marketcap_usd")
    daa = _latest("daily_active_addresses")
    vol_mcap = ((_latest("volume_usd") or 0) / mcap) if mcap and mcap > 0 else None

    derived = compute_token_derived(
        price_series=price_vals,
        btc_price_series=btc_prices if btc_prices else None,
        mvrv_series=_vals("mvrv_usd") or None,
        nvt_series=_vals("nvt") or None,
        inflow_series=_vals("exchange_inflow") or None,
        outflow_series=_vals("exchange_outflow") or None,
        mcap=mcap,
        daa=daa,
        dev_activity_val=_latest("dev_activity"),
        supply_on=_latest("supply_on_exchanges"),
        supply_outside=_latest("supply_outside_exchanges"),
        price_change_7d=price_change_7d,
        price_change_30d=price_change_30d,
        volume_change=volume_change,
        daa_change=_pct_change(_vals("daily_active_addresses"), 1),
        dev_change=_pct_change(_vals("dev_activity"), 1),
        growth_change=_pct_change(_vals("network_growth"), 1),
        exchange_balance_change=_pct_change(_vals("exchange_balance"), 1),
        vol_mcap_ratio=vol_mcap,
    )
    metrics_data["_derived"] = derived
    return metrics_data


def _build_screener_tokens(
    min_mcap=0, max_mcap=float("inf"),
    min_change=-999, max_change=999,
    sort_by="marketcap_usd", order="desc",
    sector="all", category="all",
    search: str = "",
    min_mvrv: float = -999, max_mvrv: float = 999,
):
    tokens = _get_all_tokens()
    if search:
        sq = search.lower().strip()
        tokens = [t for t in tokens if sq in t.get("name", "").lower() or sq in t.get("slug", "").lower() or sq in t.get("ticker", "").lower()]
    filtered = []
    for t in tokens:
        mcap = t.get("marketcap_usd") or 0
        if mcap < min_mcap or mcap > max_mcap:
            continue
        pct = t.get("price_usd_change", 0) or 0
        if pct < min_change or pct > max_change:
            continue
        if sector != "all" and t.get("sector") != sector:
            continue
        if category != "all" and t.get("category") != category:
            continue
        # MVRV range filter
        if min_mvrv > -999 or max_mvrv < 999:
            mvrv = t.get("mvrv_usd")
            if mvrv is None:
                continue
            if mvrv < min_mvrv or mvrv > max_mvrv:
                continue
        filtered.append(t)
    filtered.sort(key=lambda x: x.get(sort_by) or 0, reverse=(order == "desc"))
    return filtered


def _build_comparison_data(slugs: list[str]):
    if not _san_cache:
        return []
    results = []
    for slug in slugs:
        project = _san_cache.get_project(slug)
        if not project:
            project = {"name": slug.replace("-", " ").title(), "ticker": slug.upper()[:5]}
        metrics = _build_profile_metrics(slug)
        results.append({
            "slug": slug,
            "name": project.get("name", slug),
            "ticker": project.get("ticker", ""),
            "metrics": metrics,
        })
    return results


# ============================================================
# APP FACTORY
# ============================================================

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Crypto Analytics Dashboard",
        description="TradFi-inspired on-chain analytics powered by Santiment",
        version="4.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Theme middleware — reads ?theme= param
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class ThemeMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            theme = request.query_params.get("theme", "auto")
            set_theme(theme)
            return await call_next(request)

    app.add_middleware(ThemeMiddleware)

    # Mount static files
    static_path = os.path.join(os.path.dirname(__file__), "..", "..", "static")
    if os.path.exists(static_path):
        app.mount("/static", StaticFiles(directory=static_path), name="static")

    # Register ticker data function for header strip
    set_ticker_data_fn(_get_ticker_data)
    set_freshness_fn(lambda: _san_pull_status)

    # Custom 404 page
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(404)
    async def not_found_handler(request, exc):
        path = request.url.path
        suggestion = ""
        if path.startswith("/token/"):
            slug_attempt = path.replace("/token/", "").strip("/")
            suggestion = f'<p>Looking for a token? <a href="/screener?q={slug_attempt}" class="fbtn">{slug_attempt}</a></p>'

        popular = ""
        try:
            tokens = _get_all_tokens()[:8]
            if tokens:
                chips = "".join(
                    f'<a href="/token/{t["slug"]}" class="fbtn">{t.get("name", t["slug"])[:16]}</a>'
                    for t in tokens
                )
                popular = f'<div style="margin-top:12px"><p style="font-size:.78rem;color:var(--tx2);margin-bottom:6px">Popular tokens:</p><div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:center">{chips}</div></div>'
        except Exception:
            pass

        body = f"""
        <div class="empty" style="padding:60px 0">
            <div style="font-size:3rem">&#9888;</div>
            <h2>404 — Page Not Found</h2>
            <p>The page you're looking for doesn't exist or has been moved.</p>
            {suggestion}
            <form action="/screener" method="get" class="search-bar" style="margin:16px auto;max-width:300px">
                <input type="text" name="q" placeholder="Search tokens...">
                <button type="submit">Search</button>
            </form>
            <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap">
                <a href="/" class="fbtn on">Briefing</a>
                <a href="/explore" class="fbtn">Explore</a>
                <a href="/screener" class="fbtn">Screener</a>
                <a href="/sectors" class="fbtn">Sectors</a>
            </div>
            {popular}
        </div>"""
        return HTMLResponse(page_shell("404 Not Found", body), status_code=404)

    # ============================================================
    # SERVER-RENDERED PAGES (no JS required)
    # ============================================================

    @app.get("/", response_class=HTMLResponse)
    async def get_briefing_page():
        """Economy briefing — the daily dashboard."""
        briefing = _build_economy_briefing()
        status = _san_pull_status.get("status", "unknown")
        cache_stats = _san_cache.get_pull_stats() if _san_cache else {}
        universe_size = _san_pull_status.get("universe_size", 0)
        return render_briefing_page(briefing, status, cache_stats, universe_size, sectors=SECTORS)

    @app.get("/market", response_class=HTMLResponse)
    async def get_market_page(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PAGE_SIZE, ge=10, le=MAX_PAGE_SIZE),
        sector: str = Query(default="all"),
        q: str = Query(default=""),
        sort: str = Query(default="marketcap_usd"),
        order: str = Query(default="desc"),
        view: str = Query(default="overview"),
        tier: str = Query(default="all"),
        zone: str = Query(default="all"),
    ):
        """Unified market page — overview, screener, valuation, developers."""
        if view == "valuation":
            enriched = _build_all_tokens_for_valuation()
            if sector != "all":
                enriched = [t for t in enriched if t.get("sector") == sector]
            if zone != "all":
                from core.ssr_renderer import mvrv_zone as _mz
                zone_label_map = {"deep_value": "Deep Value", "undervalued": "Undervalued", "fair": "Fair Value",
                                 "elevated": "Elevated", "overvalued": "Overvalued", "euphoria": "Euphoria"}
                target_label = zone_label_map.get(zone, "")
                if target_label:
                    enriched = [t for t in enriched if t.get("mvrv_usd") is not None and _mz(t["mvrv_usd"])[0] == target_label]
            return render_market_page(enriched, total=len(enriched), sector=sector, sectors=SECTORS,
                                      view="valuation", zone_filter=zone)
        elif view == "developers":
            tokens = _get_all_tokens()
            dev_tokens = [t for t in tokens if t.get("dev_activity") is not None and (t.get("dev_activity") or 0) > 0]
            if sector != "all":
                dev_tokens = [t for t in dev_tokens if t.get("sector") == sector]
            dev_tokens.sort(key=lambda t: t.get("dev_activity") or 0, reverse=True)
            return render_market_page(dev_tokens[:100], total=len(dev_tokens), sector=sector, sectors=SECTORS,
                                      view="developers")
        elif view == "screener":
            tier_ranges = {
                "mega": (100e9, float("inf")), "large": (10e9, 100e9),
                "mid": (1e9, 10e9), "small": (100e6, 1e9),
                "micro": (0, 100e6), "all": (0, float("inf")),
            }
            min_mcap, max_mcap = tier_ranges.get(tier, (0, float("inf")))
            tokens = _build_screener_tokens(min_mcap, max_mcap, -999, 999, sort, order, sector, "all", search=q)
            visible_slugs = [t["slug"] for t in tokens[:200]]
            if visible_slugs and _san_cache:
                sparkline_data = _san_cache.get_timeseries_multi_slugs("price_usd", visible_slugs, limit_per_slug=7)
                for t in tokens[:200]:
                    t["sparkline_7d"] = sparkline_data.get(t["slug"], [])
            return render_market_page(tokens, total=len(tokens), sector=sector, sectors=SECTORS,
                                      search=q, sort_by=sort, order=order, view="screener", tier=tier)
        else:
            # Overview (default) — paginated token list
            tokens, total = _build_token_list(page, per_page, sector=sector, search=q, sort_by=sort, order=order)
            return render_market_page(tokens, page=page, per_page=per_page, total=total,
                                      sector=sector, sectors=SECTORS, search=q,
                                      sort_by=sort, order=order, view="overview")

    @app.get("/market/csv")
    async def get_market_csv(
        view: str = Query(default="overview"),
        sector: str = Query(default="all"),
        sort: str = Query(default="marketcap_usd"),
        order: str = Query(default="desc"),
        q: str = Query(default=""),
        tier: str = Query(default="all"),
    ):
        """Export market data as CSV."""
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf)
        if view == "developers":
            tokens = _get_all_tokens()
            dev_tokens = [t for t in tokens if (t.get("dev_activity") or 0) > 0]
            if sector != "all":
                dev_tokens = [t for t in dev_tokens if t.get("sector") == sector]
            dev_tokens.sort(key=lambda t: t.get("dev_activity") or 0, reverse=True)
            writer.writerow(["Rank", "Name", "Ticker", "Slug", "Sector", "Dev Activity", "Price USD", "Market Cap"])
            for i, t in enumerate(dev_tokens[:200], 1):
                writer.writerow([i, t.get("name", ""), t.get("ticker", ""), t.get("slug", ""),
                                t.get("sector", ""), t.get("dev_activity", 0),
                                t.get("price_usd", ""), t.get("marketcap_usd", "")])
        elif view == "valuation":
            enriched = _build_all_tokens_for_valuation()
            if sector != "all":
                enriched = [t for t in enriched if t.get("sector") == sector]
            writer.writerow(["Name", "Ticker", "Slug", "Sector", "Price USD", "MVRV", "Market Cap"])
            for t in enriched[:500]:
                writer.writerow([t.get("name", ""), t.get("ticker", ""), t.get("slug", ""),
                                t.get("sector", ""), t.get("price_usd", ""),
                                f"{t.get('mvrv_usd', 0) or 0:.4f}", t.get("marketcap_usd", "")])
        else:
            tokens, _ = _build_token_list(1, 500, sector=sector, search=q, sort_by=sort, order=order)
            writer.writerow(["Rank", "Name", "Ticker", "Slug", "Sector", "Price (USD)", "Change 24h %", "Market Cap", "Volume 24h", "MVRV"])
            for i, t in enumerate(tokens):
                writer.writerow([i + 1, t.get("name", ""), t.get("ticker", ""), t.get("slug", ""),
                                t.get("sector", ""), t.get("price_usd", ""),
                                f"{t.get('price_usd_change', ''):.2f}" if t.get("price_usd_change") is not None else "",
                                t.get("marketcap_usd", ""), t.get("volume_usd", ""),
                                f"{t.get('mvrv_usd', ''):.2f}" if t.get("mvrv_usd") is not None else ""])
        return Response(content=buf.getvalue(), media_type="text/csv",
                       headers={"Content-Disposition": f"attachment; filename=market_{view}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"})

    @app.get("/explore", response_class=HTMLResponse)
    async def get_explore_page(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PAGE_SIZE, ge=10, le=MAX_PAGE_SIZE),
        sector: str = Query(default="all"),
        category: str = Query(default="all"),
        q: str = Query(default=""),
        sort: str = Query(default="marketcap_usd"),
        order: str = Query(default="desc"),
        view: str = Query(default="full"),
    ):
        """Full token explorer with pagination, search, and sorting."""
        tokens, total = _build_token_list(page, per_page, sector=sector, category=category, search=q, sort_by=sort, order=order)
        # Get briefing data for movers summary (already cached)
        briefing = _build_economy_briefing()
        return render_explore_page(tokens, page=page, per_page=per_page, total=total,
                                   sector=sector, category=category, sectors=SECTORS, categories=CATEGORIES,
                                   search=q, briefing=briefing, sort_by=sort, order=order,
                                   view=view)

    @app.get("/explore/csv")
    async def get_explore_csv(
        sector: str = Query(default="all"),
        category: str = Query(default="all"),
        q: str = Query(default=""),
        sort: str = Query(default="marketcap_usd"),
        order: str = Query(default="desc"),
    ):
        """Export explore data as CSV."""
        tokens, _ = _build_token_list(1, 500, sector=sector, category=category, search=q, sort_by=sort, order=order)
        import csv, io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Rank", "Name", "Ticker", "Slug", "Sector", "Price (USD)", "Change 24h %", "Market Cap", "Volume 24h", "MVRV"])
        for i, t in enumerate(tokens):
            writer.writerow([
                i + 1,
                t.get("name", ""),
                t.get("ticker", ""),
                t.get("slug", ""),
                t.get("sector", ""),
                t.get("price_usd", ""),
                f"{t.get('price_usd_change', ''):.2f}" if t.get("price_usd_change") is not None else "",
                t.get("marketcap_usd", ""),
                t.get("volume_usd", ""),
                f"{t.get('mvrv_usd', ''):.2f}" if t.get("mvrv_usd") is not None else "",
            ])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=onchain_pulse_tokens.csv"},
        )

    @app.get("/insights", response_class=HTMLResponse)
    async def get_insights_page(
        view: str = Query(default="mvrv_nvt", description="Scatter plot view ID"),
        sector: str = Query(default="all"),
        sort: str = Query(default="marketcap", description="Sort thesis tokens: marketcap, change, mvrv"),
    ):
        """On-chain insights — scatter plots and thesis categorization."""
        insights = _build_insights_data(view)
        # Filter scatter points by sector if requested
        if sector != "all" and insights.get("points"):
            insights = dict(insights)  # shallow copy
            insights["points"] = [p for p in insights["points"] if p.get("sector") == sector]
        # Sort thesis token lists
        sort_key_map = {
            "marketcap": lambda t: t.get("marketcap_usd") or 0,
            "change": lambda t: t.get("price_usd_change") or 0,
            "mvrv": lambda t: t.get("mvrv_usd") or 0,
        }
        sfn = sort_key_map.get(sort, sort_key_map["marketcap"])
        reverse = sort != "mvrv"  # MVRV ascending (undervalued first)
        if insights.get("thesis_tokens"):
            insights = dict(insights)
            insights["thesis_tokens"] = {
                k: sorted(v, key=sfn, reverse=reverse)
                for k, v in insights["thesis_tokens"].items()
            }
        return render_insights_page(insights, view_id=view, scatter_views=SCATTER_VIEWS,
                                    sector=sector, sectors=SECTORS, sort_by=sort)

    @app.get("/insights/export.csv")
    async def get_insights_csv(
        view: str = Query(default="mvrv_nvt"),
        sector: str = Query(default="all"),
    ):
        """Export insights scatter data as CSV."""
        insights = _build_insights_data(view)
        points = insights.get("points", [])
        if sector != "all":
            points = [p for p in points if p.get("sector") == sector]
        # Find view axes labels
        x_label, y_label = "X", "Y"
        for v in SCATTER_VIEWS:
            if v[0] == view:
                x_label = v[4] if len(v) > 4 else "X"
                y_label = v[5] if len(v) > 5 else "Y"
                break
        lines = [f"Name,Ticker,Slug,Sector,Thesis,{x_label},{y_label},Market Cap"]
        for p in points[:500]:
            name = p.get("name", "").replace(",", "")
            lines.append(f"{name},{p.get('ticker','')},{p.get('slug','')},{p.get('sector','')},{p.get('thesis','')},{p.get('x',0):.4f},{p.get('y',0):.4f},{p.get('marketcap_usd',0):.0f}")
        csv_data = "\n".join(lines)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=insights_{view}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
        )

    @app.get("/valuation", response_class=HTMLResponse)
    async def get_valuation_page(
        sector: str = Query(default="all"),
        zone: str = Query(default="all"),
    ):
        """Valuation scanner — fully server-rendered."""
        if not _san_cache:
            return render_valuation_page([])
        enriched = _build_all_tokens_for_valuation()
        if sector != "all":
            enriched = [t for t in enriched if t.get("sector") == sector]
        if zone != "all":
            from core.ssr_renderer import mvrv_zone as _mz
            zone_label_map = {"deep_value": "Deep Value", "undervalued": "Undervalued", "fair": "Fair Value",
                             "elevated": "Elevated", "overvalued": "Overvalued", "euphoria": "Euphoria"}
            target_label = zone_label_map.get(zone, "")
            if target_label:
                enriched = [t for t in enriched if t.get("mvrv_usd") is not None and _mz(t["mvrv_usd"])[0] == target_label]
        return render_valuation_page(enriched, sector=sector, sectors=SECTORS, zone_filter=zone)

    @app.get("/valuation/export.csv")
    async def get_valuation_csv(
        sector: str = Query(default="all"),
        zone: str = Query(default="all"),
    ):
        """Export valuation data as CSV."""
        if not _san_cache:
            return Response(content="No data", media_type="text/plain")
        enriched = _build_all_tokens_for_valuation()
        if sector != "all":
            enriched = [t for t in enriched if t.get("sector") == sector]
        if zone != "all":
            from core.ssr_renderer import mvrv_zone as _mz
            zone_label_map = {"deep_value": "Deep Value", "undervalued": "Undervalued", "fair": "Fair Value",
                             "elevated": "Elevated", "overvalued": "Overvalued", "euphoria": "Euphoria"}
            target_label = zone_label_map.get(zone, "")
            if target_label:
                enriched = [t for t in enriched if t.get("mvrv_usd") is not None and _mz(t["mvrv_usd"])[0] == target_label]
        lines = ["Name,Ticker,Slug,Sector,Price USD,MVRV,Zone,Market Cap"]
        for t in enriched[:500]:
            name = t.get("name", "").replace(",", "")
            mvrv = t.get("mvrv_usd") or 0
            from core.ssr_renderer import mvrv_zone as _mz2
            z_label = _mz2(mvrv)[0] if mvrv else "N/A"
            lines.append(f"{name},{t.get('ticker','')},{t.get('slug','')},{t.get('sector','')},{t.get('price_usd',0):.4f},{mvrv:.4f},{z_label},{t.get('marketcap_usd',0) or 0:.0f}")
        csv_data = "\n".join(lines)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=valuation_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
        )

    @app.get("/sync", response_class=HTMLResponse)
    async def get_sync_page():
        """Sync status — fully server-rendered."""
        cache_stats = _san_cache.get_pull_stats() if _san_cache else {}
        client_stats = _san_client.stats if _san_client else {}
        return render_sync_page(_san_pull_status, cache_stats, client_stats)

    @app.get("/compare", response_class=HTMLResponse)
    async def get_compare_page(
        tokens: str = Query(default="bitcoin,ethereum,solana", description="Comma-separated slugs"),
    ):
        """Side-by-side token comparison with charts."""
        slug_list = [s.strip() for s in tokens.split(",") if s.strip()][:5]
        comparison_data = _build_comparison_data(slug_list)
        return render_compare_page(comparison_data)

    @app.get("/compare/export.csv")
    async def get_compare_csv(
        tokens: str = Query(default="bitcoin,ethereum,solana"),
    ):
        """Export comparison data as CSV."""
        slug_list = [s.strip() for s in tokens.split(",") if s.strip()][:5]
        comparison_data = _build_comparison_data(slug_list)
        compare_metrics = ["price_usd", "marketcap_usd", "volume_usd", "mvrv_usd", "nvt",
                          "daily_active_addresses", "dev_activity", "exchange_balance"]
        header = "Metric," + ",".join(d.get("name", d["slug"]).replace(",", "") for d in comparison_data)
        lines = [header]
        for mk in compare_metrics:
            row = mk.replace("_", " ").title()
            for d in comparison_data:
                m = d.get("metrics", {}).get(mk)
                val = m.get("latest") if isinstance(m, dict) else None
                row += f",{val:.4f}" if val is not None else ",N/A"
            lines.append(row)
        csv_data = "\n".join(lines)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=compare_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
        )

    @app.get("/screener", response_class=HTMLResponse)
    async def get_screener_page(
        tier: str = Query(default="all", description="Market cap tier: mega, large, mid, small, micro, all"),
        min_change: float = Query(default=-999),
        max_change: float = Query(default=999),
        sort: str = Query(default="marketcap_usd"),
        order: str = Query(default="desc"),
        sector: str = Query(default="all"),
        category: str = Query(default="all"),
        q: str = Query(default=""),
        min_mvrv: float = Query(default=-999, description="Min MVRV filter"),
        max_mvrv: float = Query(default=999, description="Max MVRV filter"),
    ):
        """Token screener with filters and search."""
        tier_ranges = {
            "mega": (100e9, float("inf")),
            "large": (10e9, 100e9),
            "mid": (1e9, 10e9),
            "small": (100e6, 1e9),
            "micro": (0, 100e6),
            "all": (0, float("inf")),
        }
        min_mcap, max_mcap = tier_ranges.get(tier, (0, float("inf")))
        tokens = _build_screener_tokens(min_mcap, max_mcap, min_change, max_change, sort, order, sector, category, search=q, min_mvrv=min_mvrv, max_mvrv=max_mvrv)
        # Add sparklines for visible tokens (top 200)
        visible_slugs = [t["slug"] for t in tokens[:200]]
        if visible_slugs and _san_cache:
            sparkline_data = _san_cache.get_timeseries_multi_slugs("price_usd", visible_slugs, limit_per_slug=7)
            for t in tokens[:200]:
                t["sparkline_7d"] = sparkline_data.get(t["slug"], [])
        return render_screener_page(
            tokens, tier=tier, min_change=min_change, max_change=max_change,
            sort_by=sort, order=order, sector=sector, category=category,
            sectors=SECTORS, categories=CATEGORIES, search=q,
            min_mvrv=min_mvrv, max_mvrv=max_mvrv,
        )

    @app.get("/screener/export.csv")
    async def get_screener_csv(
        tier: str = Query(default="all"),
        min_change: float = Query(default=-999),
        max_change: float = Query(default=999),
        sort: str = Query(default="marketcap_usd"),
        order: str = Query(default="desc"),
        sector: str = Query(default="all"),
        category: str = Query(default="all"),
        q: str = Query(default=""),
    ):
        """Export screener data as CSV."""
        tier_ranges = {
            "mega": (100e9, float("inf")),
            "large": (10e9, 100e9),
            "mid": (1e9, 10e9),
            "small": (100e6, 1e9),
            "micro": (0, 100e6),
            "all": (0, float("inf")),
        }
        min_mcap, max_mcap = tier_ranges.get(tier, (0, float("inf")))
        tokens = _build_screener_tokens(min_mcap, max_mcap, min_change, max_change, sort, order, sector, category, search=q)
        lines = ["Name,Ticker,Slug,Sector,Price USD,24h Change %,Market Cap,Volume 24h,MVRV"]
        for t in tokens[:500]:
            name = t.get("name", "").replace(",", "")
            ticker = t.get("ticker", "")
            slug = t.get("slug", "")
            sec = t.get("sector", "")
            price = t.get("price_usd") or 0
            pct = t.get("price_usd_change") or 0
            mcap = t.get("marketcap_usd") or 0
            vol = t.get("volume_usd") or 0
            mvrv = t.get("mvrv_usd") or 0
            lines.append(f"{name},{ticker},{slug},{sec},{price:.4f},{pct:.2f},{mcap:.0f},{vol:.0f},{mvrv:.4f}")
        csv_data = "\n".join(lines)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=screener_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
        )

    @app.get("/developers", response_class=HTMLResponse)
    async def get_developers_page(
        sector: str = Query(default="all"),
    ):
        """Developer activity leaderboard."""
        tokens = _get_all_tokens()
        dev_tokens = [t for t in tokens if t.get("dev_activity") is not None and (t.get("dev_activity") or 0) > 0]
        if sector != "all":
            dev_tokens = [t for t in dev_tokens if t.get("sector") == sector]
        dev_tokens.sort(key=lambda t: t.get("dev_activity") or 0, reverse=True)
        # Add dev activity sparklines for top 100
        top_slugs = [t["slug"] for t in dev_tokens[:100]]
        if top_slugs and _san_cache:
            dev_spark = _san_cache.get_timeseries_multi_slugs("dev_activity", top_slugs, limit_per_slug=30)
            for t in dev_tokens[:100]:
                t["dev_sparkline_30d"] = dev_spark.get(t["slug"], [])
        return render_developers_page(dev_tokens[:100], sector=sector, sectors=SECTORS)

    @app.get("/developers/export.csv")
    async def get_developers_csv(
        sector: str = Query(default="all"),
    ):
        """Export developer leaderboard as CSV."""
        tokens = _get_all_tokens()
        dev_tokens = [t for t in tokens if t.get("dev_activity") is not None and (t.get("dev_activity") or 0) > 0]
        if sector != "all":
            dev_tokens = [t for t in dev_tokens if t.get("sector") == sector]
        dev_tokens.sort(key=lambda t: t.get("dev_activity") or 0, reverse=True)
        lines = ["Rank,Name,Ticker,Slug,Sector,Dev Activity,Dev Change 30d %,Price USD,Market Cap"]
        for i, t in enumerate(dev_tokens[:200], 1):
            name = t.get("name", "").replace(",", "")
            lines.append(f"{i},{name},{t.get('ticker','')},{t.get('slug','')},{t.get('sector','')},{t.get('dev_activity',0):.1f},{t.get('dev_activity_change',0) or 0:.1f},{t.get('price_usd',0) or 0:.4f},{t.get('marketcap_usd',0) or 0:.0f}")
        csv_data = "\n".join(lines)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=developers_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
        )

    @app.get("/sectors", response_class=HTMLResponse)
    async def get_sectors_page():
        """Sector overview — performance by sector."""
        tokens = _get_all_tokens()
        sector_details = {}
        for t in tokens:
            sec = t.get("sector", "other")
            if sec not in sector_details:
                sector_details[sec] = {"tokens": [], "mcap": 0, "vol": 0, "pct_sum": 0, "pct_count": 0}
            sector_details[sec]["tokens"].append(t)
            sector_details[sec]["mcap"] += t.get("marketcap_usd") or 0
            sector_details[sec]["vol"] += t.get("volume_usd") or 0
            pct = t.get("price_usd_change")
            if pct is not None:
                sector_details[sec]["pct_sum"] += pct
                sector_details[sec]["pct_count"] += 1
        # Calculate averages and sort by mcap
        for sec, data in sector_details.items():
            data["avg_change"] = data["pct_sum"] / data["pct_count"] if data["pct_count"] > 0 else 0
            data["count"] = len(data["tokens"])
            sorted_tokens = sorted(data["tokens"], key=lambda x: x.get("marketcap_usd") or 0, reverse=True)
            data["top_tokens"] = sorted_tokens[:5]
            data["all_tokens"] = sorted_tokens[:20]
        return render_sectors_page(sector_details, SECTORS)

    @app.get("/sector/{sector_key}", response_class=HTMLResponse)
    async def get_sector_detail(sector_key: str):
        """Sector detail page — tokens, stats, and MVRV breakdown for a specific sector."""
        tokens = _get_all_tokens()
        sector_tokens = [t for t in tokens if t.get("sector") == sector_key]
        if not sector_tokens:
            raise HTTPException(status_code=404, detail=f"Sector '{sector_key}' not found")
        sector_tokens.sort(key=lambda t: t.get("marketcap_usd") or 0, reverse=True)
        label = SECTORS.get(sector_key, sector_key.replace("_", " ").title())
        # Add sparklines for top tokens
        top_slugs = [t["slug"] for t in sector_tokens[:50]]
        if top_slugs and _san_cache:
            spark_data = _san_cache.get_timeseries_multi_slugs("price_usd", top_slugs, limit_per_slug=7)
            for t in sector_tokens[:50]:
                t["sparkline_7d"] = spark_data.get(t["slug"], [])
        return render_sector_detail_page(sector_tokens, sector_key, label, SECTORS)

    @app.get("/sectors/export.csv")
    async def get_sectors_csv():
        """Export sector data as CSV."""
        tokens = _get_all_tokens()
        sector_agg = {}
        for t in tokens:
            sec = t.get("sector", "other")
            if sec not in sector_agg:
                sector_agg[sec] = {"count": 0, "mcap": 0, "vol": 0, "pct_sum": 0, "pct_count": 0}
            sector_agg[sec]["count"] += 1
            sector_agg[sec]["mcap"] += t.get("marketcap_usd") or 0
            sector_agg[sec]["vol"] += t.get("volume_usd") or 0
            pct = t.get("price_usd_change")
            if pct is not None:
                sector_agg[sec]["pct_sum"] += pct
                sector_agg[sec]["pct_count"] += 1
        lines = ["Sector,Token Count,Market Cap,Volume 24h,Avg 24h Change %"]
        for sec in sorted(sector_agg, key=lambda s: sector_agg[s]["mcap"], reverse=True):
            d = sector_agg[sec]
            avg_ch = d["pct_sum"] / d["pct_count"] if d["pct_count"] > 0 else 0
            sec_label = SECTORS.get(sec, sec.replace("_", " ").title())
            lines.append(f"{sec_label},{d['count']},{d['mcap']:.0f},{d['vol']:.0f},{avg_ch:.2f}")
        csv_data = "\n".join(lines)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=sectors_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
        )

    @app.get("/watchlist", response_class=HTMLResponse)
    async def get_watchlist_page(
        tokens: str = Query(default="", description="Comma-separated slugs"),
    ):
        """Personal watchlist — bookmark to save."""
        slug_list = [s.strip() for s in tokens.split(",") if s.strip()][:50]
        if not slug_list:
            return render_watchlist_page([], [])
        all_tokens = _get_all_tokens()
        slug_map = {t["slug"]: t for t in all_tokens}
        matched = [slug_map[s] for s in slug_list if s in slug_map]
        # Add sparklines
        if matched and _san_cache:
            visible_slugs = [t["slug"] for t in matched]
            sparkline_data = _san_cache.get_timeseries_multi_slugs("price_usd", visible_slugs, limit_per_slug=7)
            for t in matched:
                t["sparkline_7d"] = sparkline_data.get(t["slug"], [])
        return render_watchlist_page(matched, slug_list)

    @app.get("/watchlist/export.csv")
    async def get_watchlist_csv(
        tokens: str = Query(default="", description="Comma-separated slugs"),
    ):
        """Export watchlist as CSV."""
        slug_list = [s.strip() for s in tokens.split(",") if s.strip()][:50]
        all_tokens = _get_all_tokens()
        slug_map = {t["slug"]: t for t in all_tokens}
        matched = [slug_map[s] for s in slug_list if s in slug_map]
        lines = ["Name,Ticker,Slug,Sector,Price USD,24h Change %,Market Cap,Volume 24h,MVRV"]
        for t in matched:
            name = t.get("name", "").replace(",", "")
            lines.append(f"{name},{t.get('ticker','')},{t.get('slug','')},{t.get('sector','')},{t.get('price_usd',0):.4f},{t.get('price_usd_change',0) or 0:.2f},{t.get('marketcap_usd',0) or 0:.0f},{t.get('volume_usd',0) or 0:.0f},{t.get('mvrv_usd',0) or 0:.4f}")
        csv_data = "\n".join(lines)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=watchlist_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
        )

    @app.get("/token/{slug}", response_class=HTMLResponse)
    async def get_token_page(
        slug: str,
        tf: str = Query(default="all", description="Timeframe: 7d, 30d, 90d, 1y, all"),
    ):
        """Token profile — fully server-rendered with deep metrics."""
        if not _san_cache:
            return HTMLResponse("<html><body><h1>Data not available yet</h1><a href='/'>Back</a></body></html>")

        project = _san_cache.get_project(slug)
        if not project:
            project = {"name": slug.replace("-", " ").title(), "ticker": slug.upper()[:5]}

        # Fetch slightly more than displayed so derived metrics have lookback data
        tf_limit = {"7d": 60, "30d": 90, "90d": 180, "1y": 400, "all": 0}.get(tf, 0)
        metrics = _build_profile_metrics(slug, limit_days=tf_limit)
        if not metrics:
            return HTMLResponse(f"<html><body><h1>No data for {slug}</h1><p>Data may still be loading.</p><a href='/'>Back</a></body></html>")

        # Trim timeseries to requested timeframe for display
        tf_days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365, "all": 0}.get(tf, 0)
        if tf_days > 0:
            for key, mdata in metrics.items():
                if isinstance(mdata, dict) and mdata.get("data"):
                    mdata["data"] = mdata["data"][-tf_days:]

        # Find sector info and related tokens
        token_info = None
        related_tokens = []
        all_tokens = _get_all_tokens()
        for t in all_tokens:
            if t.get("slug") == slug:
                token_info = t
                break
        if token_info:
            sec = token_info.get("sector", "other")
            related_tokens = [t for t in all_tokens if t.get("sector") == sec and t.get("slug") != slug][:8]
            # Fetch sparklines for related tokens
            if related_tokens and _san_cache:
                rel_slugs = [rt["slug"] for rt in related_tokens if rt.get("slug")]
                if rel_slugs:
                    spark_data = _san_cache.get_timeseries_multi_slugs("price_usd", rel_slugs, limit_per_slug=7)
                    for rt in related_tokens:
                        rt["sparkline_7d"] = spark_data.get(rt["slug"], [])

        # Prev/next token navigation (by market cap rank)
        prev_token = None
        next_token = None
        mcap_rank = None
        for i, t in enumerate(all_tokens):
            if t.get("slug") == slug:
                mcap_rank = i + 1
                if i > 0:
                    prev_token = {"slug": all_tokens[i-1]["slug"], "name": all_tokens[i-1].get("name", "")}
                if i < len(all_tokens) - 1:
                    next_token = {"slug": all_tokens[i+1]["slug"], "name": all_tokens[i+1].get("name", "")}
                break

        return render_token_profile(project, metrics, slug, timeframe=tf, token_info=token_info, related_tokens=related_tokens, prev_token=prev_token, next_token=next_token, mcap_rank=mcap_rank, all_tokens=all_tokens)

    @app.get("/glossary", response_class=HTMLResponse)
    async def get_glossary_page():
        """Metric glossary — explanations of all on-chain metrics."""
        return render_glossary_page()

    @app.get("/quant", response_class=HTMLResponse)
    async def get_quant_page():
        """Quantitative analytics — correlation matrix, sector rotation, mean reversion scanner."""
        if not _san_cache:
            return HTMLResponse("<html><body><h1>Data not available yet</h1></body></html>")

        all_tokens = _get_all_tokens()

        # 1. Correlation matrix — top 15 tokens by market cap
        top_slugs = [t["slug"] for t in sorted(all_tokens, key=lambda x: x.get("marketcap_usd") or 0, reverse=True)[:15]]
        price_series_dict = {}
        corr_labels = {}
        for slug in top_slugs:
            ts = _san_cache.get_timeseries("price_usd", slug)
            prices = [d["value"] for d in ts if d.get("value") is not None]
            if len(prices) >= 30:
                price_series_dict[slug] = prices
                proj = _san_cache.get_project(slug)
                corr_labels[slug] = (proj.get("ticker") or slug[:5].upper()) if proj else slug[:5].upper()

        corr_mat = correlation_matrix(price_series_dict, window=90) if len(price_series_dict) >= 2 else None

        # 2. Sector rotation
        sec_rot = sector_momentum(all_tokens)

        # 3. Mean reversion scanner — find tokens with extreme z-scores
        mean_rev_tokens = []
        for t in all_tokens[:200]:  # Top 200 by mcap
            slug = t.get("slug", "")
            mvrv_ts = _san_cache.get_timeseries("mvrv_usd", slug)
            nvt_ts = _san_cache.get_timeseries("nvt", slug)
            mvrv_vals = [d["value"] for d in mvrv_ts if d.get("value") is not None]
            nvt_vals = [d["value"] for d in nvt_ts if d.get("value") is not None]

            mvrv_z = mean_reversion_zscore(mvrv_vals) if len(mvrv_vals) >= 30 else None
            nvt_z = mean_reversion_zscore(nvt_vals) if len(nvt_vals) >= 30 else None

            # Only include if at least one z-score is extreme
            if (mvrv_z is not None and abs(mvrv_z) >= 1.5) or (nvt_z is not None and abs(nvt_z) >= 1.5):
                signal = ""
                if mvrv_z is not None and mvrv_z <= -1.5:
                    signal = "Undervalued (MVRV stretched low)"
                elif mvrv_z is not None and mvrv_z >= 2:
                    signal = "Overvalued (MVRV stretched high)"
                elif nvt_z is not None and nvt_z <= -1.5:
                    signal = "High usage efficiency (NVT low)"
                elif nvt_z is not None and nvt_z >= 2:
                    signal = "Low usage efficiency (NVT high)"
                mean_rev_tokens.append({
                    **t, "mvrv_zscore_1y": mvrv_z, "nvt_zscore_1y": nvt_z, "signal": signal,
                })
        mean_rev_tokens.sort(key=lambda x: abs(x.get("mvrv_zscore_1y") or 0), reverse=True)

        # 4. Risk-adjusted rankings
        risk_adj = []
        btc_ts = _san_cache.get_timeseries("price_usd", "bitcoin")
        btc_prices = [d["value"] for d in btc_ts if d.get("value") is not None]
        for t in all_tokens[:100]:
            slug = t.get("slug", "")
            ts = _san_cache.get_timeseries("price_usd", slug)
            prices = [d["value"] for d in ts if d.get("value") is not None]
            if len(prices) < 30:
                continue
            s90 = sortino_ratio(prices, 90) if len(prices) >= 90 else None
            c90 = calmar_ratio(prices, 90) if len(prices) >= 30 else None
            from core.derived_metrics import sharpe_ratio as _sharpe
            sh90 = _sharpe(prices, 90) if len(prices) >= 90 else None
            daa = t.get("daily_active_addresses") or 0
            mcap = t.get("marketcap_usd") or 0
            met = metcalfe_ratio(daa, mcap)
            if s90 is not None:
                risk_adj.append({
                    **t, "sortino_90d": s90, "calmar_90d": c90,
                    "sharpe_90d": sh90, "metcalfe_ratio": met,
                })
        risk_adj.sort(key=lambda x: x.get("sortino_90d") or -999, reverse=True)

        return render_quant_page(
            corr_matrix=corr_mat, corr_labels=corr_labels,
            sector_rotation=sec_rot, mean_reversion=mean_rev_tokens[:30],
            risk_adjusted=risk_adj,
        )

    # ============================================================
    # JSON API ENDPOINTS (for programmatic access)
    # ============================================================

    @app.get("/api", response_class=HTMLResponse)
    async def get_api_docs():
        """API documentation page."""
        endpoints = [
            ("GET", "/api/v1/market", "Paginated token list with latest metrics",
             "page=1, per_page=100", '{"tokens": [...], "total": 3500, "page": 1}'),
            ("GET", "/api/v1/profile/{slug}", "Full token profile with all metrics",
             "slug (path)", '{"project": {...}, "metrics": {...}}'),
            ("GET", "/api/v1/metric/{metric}", "Timeseries data for a specific metric",
             "metric (path), slug (required), from_date, to_date",
             '{"metric": "...", "slug": "...", "data": [...]}'),
            ("GET", "/api/v1/valuation/{slug}", "Valuation summary with 90d/365d averages",
             "slug (path)", '{"slug": "...", "valuation": {...}}'),
            ("GET", "/api/v1/status", "System status and data pull progress",
             "none", '{"pull_status": {...}, "cache_stats": {...}}'),
            ("GET", "/explore/csv", "Export explore data as CSV download",
             "sector, category, q, sort, order", "CSV file download"),
        ]
        rows = ""
        for method, path, desc, params, response in endpoints:
            try_path = path.replace("{slug}", "bitcoin").replace("{metric}", "price_usd")
            if "?" not in try_path and "csv" not in try_path:
                try_link = f'<a href="{try_path}" class="fbtn" target="_blank">Try &rarr;</a>'
            else:
                try_link = ""
            rows += f"""<tr>
                <td><span class="bold">{method}</span></td>
                <td class="col-nm"><code>{_esc(path)}</code> {try_link}</td>
                <td>{_esc(desc)}</td>
                <td class="hide-m"><code>{_esc(params)}</code></td>
                <td class="hide-m"><code>{_esc(response)[:60]}...</code></td>
            </tr>"""
        body = f"""
        <h1 class="pg-t">API Documentation</h1>
        <p class="pg-sub">JSON endpoints for programmatic access to on-chain data</p>
        <div class="card" style="padding:16px">
            <p style="font-size:.8rem;margin-bottom:12px">Base URL: <code>https://santimentstuff-production-2305.up.railway.app</code></p>
            <p style="font-size:.75rem;color:var(--tx2);margin-bottom:12px">All endpoints return JSON unless otherwise noted. No authentication required.</p>
        </div>
        <div class="tbl-w">
            <table>
                <thead><tr>
                    <th>Method</th><th>Endpoint</th><th>Description</th>
                    <th class="hide-m">Parameters</th><th class="hide-m">Response</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
        <div class="card" style="padding:16px;margin-top:16px">
            <div class="card-t">Example Usage</div>
            <pre style="font-size:.75rem;overflow-x:auto;padding:10px;background:var(--bg2);border-radius:4px;margin-top:8px"><code>curl https://santimentstuff-production-2305.up.railway.app/api/v1/market?page=1&amp;per_page=10

curl https://santimentstuff-production-2305.up.railway.app/api/v1/profile/bitcoin

curl https://santimentstuff-production-2305.up.railway.app/api/v1/metric/mvrv_usd?slug=ethereum

curl https://santimentstuff-production-2305.up.railway.app/api/v1/briefing

curl https://santimentstuff-production-2305.up.railway.app/api/v1/sectors

curl https://santimentstuff-production-2305.up.railway.app/api/v1/valuation/bitcoin</code></pre>
        </div>
        <div class="card" style="padding:16px;margin-top:16px">
            <div class="card-t">Python Example</div>
            <pre style="font-size:.75rem;overflow-x:auto;padding:10px;background:var(--bg2);border-radius:4px;margin-top:8px"><code>import requests

BASE = "https://santimentstuff-production-2305.up.railway.app"

# Get market overview
market = requests.get(f"{{BASE}}/api/v1/market?per_page=10").json()
for token in market["tokens"]:
    print(f"{{token['name']}}: ${{token['price_usd']:.2f}}")

# Get Bitcoin profile
btc = requests.get(f"{{BASE}}/api/v1/profile/bitcoin").json()
print(f"BTC MVRV: {{btc['metrics']['mvrv_usd']['latest']:.2f}}")

# Get MVRV timeseries for Ethereum
eth_mvrv = requests.get(f"{{BASE}}/api/v1/metric/mvrv_usd?slug=ethereum").json()
for d in eth_mvrv["data"][-5:]:
    print(f"{{d['datetime']}}: {{d['value']:.2f}}")</code></pre>
        </div>
        <div class="card" style="padding:16px;margin-top:16px">
            <div class="card-t">Rate Limits</div>
            <p style="font-size:.78rem;color:var(--tx2)">No authentication or API keys required. Data refreshes daily. Be reasonable with request frequency. All data sourced from <a href="https://santiment.net" target="_blank" rel="noopener">Santiment API</a>.</p>
        </div>"""
        return page_shell("API Documentation", body)

    @app.get("/api/v1/market")
    async def get_market_overview(
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=DEFAULT_PAGE_SIZE, ge=10, le=MAX_PAGE_SIZE),
    ):
        """JSON: all tokens with latest metrics (paginated)."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")
        tokens, total = _build_token_list(page, per_page)
        total_pages = (total + per_page - 1) // per_page
        return {
            "tokens": tokens,
            "count": len(tokens),
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "pull_status": _san_pull_status.get("status", "unknown"),
            "last_pull": _san_pull_status.get("last_pull"),
            "universe_size": _san_pull_status.get("universe_size", 0),
        }

    @app.get("/api/v1/profile/{slug}")
    async def get_token_profile_api(slug: str):
        """JSON: full token profile."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")
        project = _san_cache.get_project(slug)
        if not project:
            raise HTTPException(404, f"Project '{slug}' not found")
        metrics = _build_profile_metrics(slug)
        return {"project": project, "metrics": metrics}

    @app.get("/api/v1/metric/{metric}")
    async def get_metric(
        metric: str,
        slug: str = Query(..., description="Token slug"),
        from_date: Optional[str] = Query(default=None),
        to_date: Optional[str] = Query(default=None),
    ):
        """JSON: timeseries data for a specific metric."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")
        data = _san_cache.get_timeseries(metric, slug, from_date, to_date)
        return {"metric": metric, "slug": slug, "data": data, "count": len(data)}

    @app.get("/api/v1/valuation/{slug}")
    async def get_valuation(slug: str):
        """JSON: valuation summary."""
        if not _san_cache:
            raise HTTPException(503, "Santiment not configured")
        valuation_metrics = ["mvrv_usd", "nvt", "price_usd", "marketcap_usd", "volume_usd"]
        result = {}
        for metric in valuation_metrics:
            data = _san_cache.get_timeseries(metric, slug)
            if data:
                values = [d["value"] for d in data if d.get("value") is not None]
                result[metric] = {
                    "current": values[-1] if values else None,
                    "avg_90d": round(sum(values[-90:]) / len(values[-90:]), 2) if len(values) >= 90 else None,
                    "avg_365d": round(sum(values[-365:]) / len(values[-365:]), 2) if len(values) >= 365 else None,
                    "min_365d": min(values[-365:]) if len(values) >= 365 else None,
                    "max_365d": max(values[-365:]) if len(values) >= 365 else None,
                }
        return {"slug": slug, "valuation": result}

    @app.get("/api/v1/briefing")
    async def get_briefing_api():
        """JSON: economy briefing summary."""
        b = _build_economy_briefing()
        if not b:
            raise HTTPException(503, "Briefing data not available")
        breadth = b.get("breadth", {})
        return {
            "total_tokens": b.get("total_tokens", 0),
            "total_mcap": b.get("total_mcap"),
            "total_volume": b.get("total_vol"),
            "avg_mvrv": b.get("avg_mvrv"),
            "breadth": breadth,
            "breadth_pct": (breadth.get("up", 0) / (breadth.get("up", 0) + breadth.get("down", 1)) * 100) if breadth else None,
            "mvrv_zones": b.get("mvrv_zones", {}),
            "vol_concentration_top10": b.get("vol_concentration_top10"),
            "accumulating": b.get("accumulating"),
            "distributing": b.get("distributing"),
            "total_daa": b.get("total_daa"),
            "total_dev": b.get("total_dev"),
            "signals_count": len(b.get("signals", [])),
            "gainers_count": len(b.get("gainers", [])),
            "losers_count": len(b.get("losers", [])),
        }

    @app.get("/api/v1/sectors")
    async def get_sectors_api():
        """JSON: sector breakdown."""
        tokens = _get_all_tokens()
        sector_agg = {}
        for t in tokens:
            sec = t.get("sector", "other")
            if sec not in sector_agg:
                sector_agg[sec] = {"label": SECTORS.get(sec, sec), "count": 0, "mcap": 0, "vol": 0, "up": 0, "down": 0}
            sector_agg[sec]["count"] += 1
            sector_agg[sec]["mcap"] += t.get("marketcap_usd") or 0
            sector_agg[sec]["vol"] += t.get("volume_usd") or 0
            chg = t.get("price_usd_change") or 0
            if chg > 0:
                sector_agg[sec]["up"] += 1
            elif chg < 0:
                sector_agg[sec]["down"] += 1
        return {"sectors": sector_agg, "total_tokens": len(tokens)}

    # ============================================================
    # SEO — SITEMAP + ROBOTS
    # ============================================================

    @app.get("/sitemap.xml", response_class=Response)
    async def sitemap():
        """Dynamic sitemap for SEO."""
        base = "https://santimentstuff-production-2305.up.railway.app"
        urls = [
            (f"{base}/", "daily", "1.0"),
            (f"{base}/explore", "daily", "0.8"),
            (f"{base}/screener", "daily", "0.8"),
            (f"{base}/valuation", "daily", "0.8"),
            (f"{base}/insights", "daily", "0.7"),
            (f"{base}/sectors", "daily", "0.7"),
            (f"{base}/developers", "daily", "0.7"),
            (f"{base}/compare", "weekly", "0.6"),
            (f"{base}/glossary", "monthly", "0.5"),
            (f"{base}/sync", "always", "0.3"),
        ]
        # Add sector detail pages
        for sec_key in SECTORS:
            urls.append((f"{base}/sector/{sec_key}", "daily", "0.6"))
        # Add individual token pages
        all_tokens = _get_all_tokens()
        for t in sorted(all_tokens, key=lambda x: x.get("marketcap_usd") or 0, reverse=True)[:200]:
            slug = t.get("slug", "")
            if slug:
                urls.append((f"{base}/token/{slug}", "daily", "0.6"))
        entries = "\n".join(
            f"  <url><loc>{loc}</loc><changefreq>{freq}</changefreq><priority>{pri}</priority></url>"
            for loc, freq, pri in urls
        )
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>"""
        return Response(content=xml, media_type="application/xml")

    @app.get("/robots.txt", response_class=Response)
    async def robots():
        """Robots.txt for SEO."""
        base = "https://santimentstuff-production-2305.up.railway.app"
        return Response(
            content=f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n",
            media_type="text/plain",
        )

    # ============================================================
    # SYSTEM ENDPOINTS
    # ============================================================

    @app.get("/api/v1/status")
    async def get_status():
        """System status and pull progress."""
        db_path = _san_cache._db_path if _san_cache else None
        volume_mounted = os.path.isdir("/data")
        return {
            "pull_status": _san_pull_status,
            "cache_stats": _san_cache.get_pull_stats() if _san_cache else None,
            "client_stats": _san_client.stats if _san_client else None,
            "storage": {
                "db_path": db_path,
                "volume_mounted": volume_mounted,
                "persistent": db_path.startswith("/data") if db_path else False,
            },
        }

    @app.post("/api/v1/retry")
    async def retry_pull():
        """Trigger a data pull retry."""
        global _san_pull_status
        if not _san_client or not _san_puller:
            raise HTTPException(503, "Santiment not configured")
        if _san_pull_status.get("status") in ("phase1_pulling", "phase2_universe", "phase3_deep"):
            return {"message": "Pull already in progress"}
        asyncio.create_task(_santiment_background_pull())
        return {"message": "Pull retry triggered"}

    @app.get("/health")
    async def health_check():
        """Health check."""
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "santiment": _san_pull_status.get("status", "not_configured"),
            "universe_size": _san_pull_status.get("universe_size", 0),
        }

    return app


app = create_app()
