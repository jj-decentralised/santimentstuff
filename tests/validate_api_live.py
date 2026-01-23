"""
Live API Validation Script.

Run this BEFORE deployment per NOTES.md requirements.

Usage:
    NANSEN_API_KEY=your_key python -m tests.validate_api_live
"""

import asyncio
import os
import sys
from datetime import datetime


async def validate_api():
    """Validate live API access and data rendering."""

    api_key = os.environ.get("NANSEN_API_KEY")
    if not api_key:
        print("ERROR: NANSEN_API_KEY environment variable required")
        print("Usage: NANSEN_API_KEY=your_key python -m tests.validate_api_live")
        sys.exit(1)

    print(f"Starting API validation at {datetime.now().isoformat()}")
    print("=" * 60)

    errors = []

    # Import after checking key to avoid import errors
    from core.nansen_client import NansenClient
    from core.nansen_models import VALID_CHAINS

    async with NansenClient(api_key=api_key) as client:

        # Test 1: Smart Money Holdings
        print("\n[Test 1] Smart Money Holdings...")
        try:
            holdings = await client.get_smart_money_holdings(["ethereum"], 5)
            if not holdings:
                errors.append("Holdings returned empty data")
            else:
                print(f"  OK - Retrieved {len(holdings)} holdings")
                print(f"  Sample: {holdings[0].token_symbol} - ${holdings[0].value_usd:,.0f}")
        except Exception as e:
            errors.append(f"Holdings failed: {e}")
            print(f"  FAILED: {e}")

        # Test 2: DEX Trades
        print("\n[Test 2] Smart Money DEX Trades...")
        try:
            trades = await client.get_dex_trades(["ethereum"], 5)
            if not trades:
                errors.append("DEX trades returned empty data")
            else:
                print(f"  OK - Retrieved {len(trades)} trades")
                buy_count = sum(1 for t in trades if t.is_buy)
                print(f"  Buys: {buy_count}, Sells: {len(trades) - buy_count}")
        except Exception as e:
            errors.append(f"DEX trades failed: {e}")
            print(f"  FAILED: {e}")

        # Test 3: Token Holders (TGM)
        print("\n[Test 3] Token Holders (TGM)...")
        try:
            # Use UNI token for testing
            test_token = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"
            holders = await client.get_token_holders(test_token, "ethereum", 5)
            if not holders:
                errors.append("Token holders returned empty data")
            else:
                print(f"  OK - Retrieved {len(holders)} holders for UNI")
                if holders:
                    print(f"  Top holder: {holders[0].address_label[:30]}...")
        except Exception as e:
            errors.append(f"Token holders failed: {e}")
            print(f"  FAILED: {e}")

        # Test 4: Flow Intelligence
        print("\n[Test 4] Flow Intelligence...")
        try:
            test_token = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"
            flows = await client.get_flow_intelligence(test_token, "ethereum")
            print(f"  OK - Retrieved flow intelligence")
            print(f"  Smart Money Net Flow: ${flows.smart_trader_net_flow_usd:,.0f}")
            print(f"  Whale Net Flow: ${flows.whale_net_flow_usd:,.0f}")
        except Exception as e:
            errors.append(f"Flow intelligence failed: {e}")
            print(f"  FAILED: {e}")

        # Test 5: Chain/Config Validation
        print("\n[Test 5] Chain/Config Validation...")
        test_chains = ["ethereum", "solana"]
        for chain in test_chains:
            if chain in VALID_CHAINS:
                print(f"  OK - {chain} is a valid chain")
            else:
                errors.append(f"Chain {chain} not in VALID_CHAINS")
                print(f"  FAILED - {chain} not valid")

    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"VALIDATION FAILED - {len(errors)} errors:")
        for e in errors:
            print(f"  - {e}")
        print("\nDO NOT DEPLOY - Fix errors first per NOTES.md")
        sys.exit(1)
    else:
        print("VALIDATION PASSED - All API tests successful")
        print("Safe to proceed with deployment")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(validate_api())
