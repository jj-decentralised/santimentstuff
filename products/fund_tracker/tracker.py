"""Fund portfolio tracking with cost basis and P/L calculations."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from core.arkham_client import ArkhamClient
from core.arkham_models import (
    Fund,
    TokenHolding,
    Transfer,
    FlowData,
    CostBasis,
    PnLSummary,
    Portfolio,
)


@dataclass
class TokenAcquisition:
    """Track individual token acquisitions for FIFO cost basis."""
    timestamp: datetime
    amount: float
    cost_usd: float
    price_per_unit: float


class FundTracker:
    """Track fund portfolios with cost basis and P/L analysis."""

    def __init__(self, client: ArkhamClient):
        self.client = client

    async def get_available_funds(self) -> list[Fund]:
        """Get list of available funds to track."""
        return await self.client.get_available_funds()

    async def get_fund_holdings(self, entity_id: str) -> list[TokenHolding]:
        """Get current holdings for a fund."""
        return await self.client.get_portfolio(entity_id)

    async def get_fund_transfers(
        self,
        entity_id: str,
        limit: int = 500,
    ) -> list[Transfer]:
        """Get transfer history for a fund."""
        return await self.client.get_transfers(entity_id, limit=limit)

    async def calculate_cost_basis(
        self,
        entity_id: str,
        holdings: list[TokenHolding] | None = None,
        transfers: list[Transfer] | None = None,
    ) -> dict[str, CostBasis]:
        """
        Calculate cost basis for all positions using average cost method.

        For each token:
        - Sum all inflows (buys) with their historical USD value
        - Sum all outflows (sells) with their historical USD value
        - Calculate average cost per unit
        """
        if holdings is None:
            holdings = await self.get_fund_holdings(entity_id)

        if transfers is None:
            transfers = await self.get_fund_transfers(entity_id, limit=500)

        # Filter out transfers with no meaningful value
        transfers = [t for t in transfers if t.historical_usd > 0 or t.amount > 0]

        # Group transfers by token
        token_transfers: dict[str, list[Transfer]] = defaultdict(list)
        for t in transfers:
            token_transfers[t.token_symbol].append(t)

        # Calculate cost basis for each held token
        cost_basis_map = {}
        holdings_by_symbol = {h.symbol: h for h in holdings}

        for symbol, txs in token_transfers.items():
            total_acquired = 0.0
            total_cost = 0.0
            total_disposed = 0.0
            total_proceeds = 0.0

            for tx in sorted(txs, key=lambda x: x.timestamp):
                if tx.direction == "in":
                    total_acquired += tx.amount
                    total_cost += tx.historical_usd
                else:
                    total_disposed += tx.amount
                    total_proceeds += tx.historical_usd

            current_balance = total_acquired - total_disposed
            avg_cost = total_cost / total_acquired if total_acquired > 0 else 0

            # Get token_id from holdings if available
            holding = holdings_by_symbol.get(symbol)
            token_id = holding.token_id if holding else symbol.lower()

            cost_basis_map[symbol] = CostBasis(
                token_id=token_id,
                symbol=symbol,
                total_acquired=total_acquired,
                total_cost_usd=total_cost,
                total_disposed=total_disposed,
                total_proceeds_usd=total_proceeds,
                current_balance=current_balance,
                avg_cost_per_unit=avg_cost,
            )

        return cost_basis_map

    async def calculate_pnl(
        self,
        holdings: list[TokenHolding],
        cost_basis: dict[str, CostBasis],
    ) -> list[PnLSummary]:
        """Calculate P/L for each position."""
        pnl_list = []

        for holding in holdings:
            cb = cost_basis.get(holding.symbol)

            if cb and cb.total_acquired > 0:
                # Calculate unrealized P/L
                # Current value - (avg cost * current balance)
                implied_cost = cb.avg_cost_per_unit * holding.balance
                unrealized_pnl = holding.value_usd - implied_cost
                unrealized_pnl_pct = (
                    (unrealized_pnl / implied_cost * 100) if implied_cost > 0 else 0
                )

                # Realized P/L from sales
                realized_pnl = cb.total_proceeds_usd - (
                    cb.avg_cost_per_unit * cb.total_disposed
                )
            else:
                # No transfer history - can't calculate cost basis
                unrealized_pnl = 0
                unrealized_pnl_pct = 0
                realized_pnl = 0
                implied_cost = 0

            pnl_list.append(
                PnLSummary(
                    token_id=holding.token_id,
                    symbol=holding.symbol,
                    current_value=holding.value_usd,
                    cost_basis=implied_cost,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    realized_pnl=realized_pnl,
                )
            )

        # Sort by absolute unrealized P/L
        pnl_list.sort(key=lambda x: abs(x.unrealized_pnl), reverse=True)
        return pnl_list

    async def get_full_portfolio(self, entity_id: str) -> Portfolio | None:
        """Get complete portfolio with holdings, cost basis, and P/L."""
        fund = await self.client.get_entity(entity_id)
        if not fund:
            return None

        holdings = await self.get_fund_holdings(entity_id)
        transfers = await self.get_fund_transfers(entity_id, limit=1000)

        cost_basis = await self.calculate_cost_basis(
            entity_id, holdings=holdings, transfers=transfers
        )
        pnl = await self.calculate_pnl(holdings, cost_basis)

        total_value = sum(h.value_usd for h in holdings)

        return Portfolio(
            fund=fund,
            holdings=holdings,
            total_value_usd=total_value,
            cost_basis_by_token=cost_basis,
            pnl_summary=pnl,
        )

    async def get_fund_comparison(
        self, entity_ids: list[str]
    ) -> list[dict]:
        """Compare multiple funds side by side."""
        comparisons = []

        for entity_id in entity_ids:
            portfolio = await self.get_full_portfolio(entity_id)
            if portfolio:
                comparisons.append({
                    "fund_id": entity_id,
                    "fund_name": portfolio.fund.name,
                    "total_value": portfolio.total_value_usd,
                    "total_pnl": portfolio.total_unrealized_pnl,
                    "total_pnl_pct": portfolio.total_pnl_pct,
                    "top_holdings": [
                        {
                            "symbol": h.symbol,
                            "value": h.value_usd,
                            "pct_of_portfolio": (
                                h.value_usd / portfolio.total_value_usd * 100
                                if portfolio.total_value_usd > 0
                                else 0
                            ),
                        }
                        for h in portfolio.holdings[:5]
                    ],
                    "position_count": len(portfolio.holdings),
                })

        # Sort by total value
        comparisons.sort(key=lambda x: x["total_value"], reverse=True)
        return comparisons

    async def get_flow_history(self, entity_id: str) -> dict[str, FlowData]:
        """Get historical flow data for a fund."""
        return await self.client.get_flow(entity_id)

    async def get_recent_activity(
        self, entity_id: str, limit: int = 20
    ) -> list[dict]:
        """Get recent transfer activity formatted for display."""
        transfers = await self.client.get_transfers(entity_id, limit=limit)

        activity = []
        for t in transfers:
            activity.append({
                "timestamp": t.timestamp.isoformat(),
                "type": "Received" if t.direction == "in" else "Sent",
                "token": t.token_symbol,
                "amount": t.amount,
                "value_usd": t.historical_usd,
                "counterparty": t.counterparty_entity or t.counterparty[:10] + "..." if t.counterparty else "Unknown",
                "chain": t.chain,
                "tx_hash": t.tx_hash,
            })

        return activity
