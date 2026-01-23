"""Test Arkham API integration."""

import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.arkham_client import ArkhamClient
from products.fund_tracker.tracker import FundTracker


async def test_api():
    """Test basic API functionality."""
    api_key = os.environ.get("ARKHAM_API_KEY", "")
    if not api_key:
        print("ERROR: ARKHAM_API_KEY environment variable not set")
        return False

    print("Testing Arkham API integration...\n")

    async with ArkhamClient(api_key=api_key) as client:
        tracker = FundTracker(client)

        # Test 1: Get available funds
        print("1. Testing get_available_funds()...")
        funds = await tracker.get_available_funds()
        print(f"   Found {len(funds)} funds:")
        for f in funds[:5]:
            print(f"   - {f.name} ({f.id})")
        print()

        if not funds:
            print("   No funds found, testing with 'a16z' directly...")
            test_fund = "a16z"
        else:
            test_fund = funds[0].id

        # Test 2: Get fund holdings
        print(f"2. Testing get_fund_holdings('{test_fund}')...")
        holdings = await tracker.get_fund_holdings(test_fund)
        total_value = sum(h.value_usd for h in holdings)
        print(f"   Total holdings: {len(holdings)}")
        print(f"   Total value: ${total_value:,.2f}")
        if holdings:
            print(f"   Top 3 holdings:")
            for h in holdings[:3]:
                print(f"   - {h.symbol}: ${h.value_usd:,.2f}")
        print()

        # Test 3: Get transfers
        print(f"3. Testing get_fund_transfers('{test_fund}')...")
        transfers = await tracker.get_fund_transfers(test_fund, limit=10)
        print(f"   Found {len(transfers)} transfers")
        if transfers:
            t = transfers[0]
            print(f"   Latest: {t.direction} {t.amount} {t.token_symbol} (${t.historical_usd:,.2f})")
        print()

        # Test 4: Calculate cost basis
        print(f"4. Testing calculate_cost_basis('{test_fund}')...")
        cost_basis = await tracker.calculate_cost_basis(
            test_fund, holdings=holdings, transfers=transfers
        )
        print(f"   Cost basis calculated for {len(cost_basis)} tokens")
        for symbol, cb in list(cost_basis.items())[:3]:
            print(f"   - {symbol}: avg cost ${cb.avg_cost_per_unit:.4f}")
        print()

        # Test 5: Full portfolio
        print(f"5. Testing get_full_portfolio('{test_fund}')...")
        portfolio = await tracker.get_full_portfolio(test_fund)
        if portfolio:
            print(f"   Fund: {portfolio.fund.name}")
            print(f"   Total Value: ${portfolio.total_value_usd:,.2f}")
            print(f"   Total Cost Basis: ${portfolio.total_cost_basis:,.2f}")
            print(f"   Unrealized P/L: ${portfolio.total_unrealized_pnl:,.2f}")
            print(f"   P/L %: {portfolio.total_pnl_pct:.2f}%")
        print()

        print("All tests passed!")
        return True


if __name__ == "__main__":
    success = asyncio.run(test_api())
    sys.exit(0 if success else 1)
