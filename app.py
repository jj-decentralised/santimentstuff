"""Fund Portfolio Tracker - Simple FastAPI app."""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core import arkham_client as arkham

# Paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

# App
app = FastAPI(title="Fund Portfolio Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Dashboard page."""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/health")
def health():
    """Health check."""
    key = os.environ.get("ARKHAM_API_KEY", "")
    return {
        "status": "ok",
        "api_key_set": bool(key),
        "api_key_preview": key[:8] + "..." if key else "NOT SET",
    }


@app.get("/api/funds")
def get_funds():
    """List all funds."""
    funds = arkham.list_funds()
    return {"funds": funds}


@app.get("/api/fund/{fund_id}")
def get_fund(fund_id: str):
    """Get fund details with holdings and P/L."""
    # Get entity info
    entity = arkham.get_entity(fund_id)
    if not entity:
        return {"error": "Fund not found"}

    # Get portfolio
    raw_portfolio = arkham.get_portfolio(fund_id)
    holdings = arkham.parse_portfolio(raw_portfolio)

    # Get transfers for cost basis
    raw_transfers = arkham.get_transfers(fund_id, limit=200)

    # Calculate cost basis and P/L
    holdings_with_pnl = arkham.calculate_cost_basis(holdings, raw_transfers)

    # Totals
    total_value = sum(h["value_usd"] for h in holdings_with_pnl)
    total_cost = sum(h["cost_basis"] for h in holdings_with_pnl)
    total_pnl = sum(h["pnl"] for h in holdings_with_pnl)
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    return {
        "fund": {
            "id": entity.get("id"),
            "name": entity.get("name"),
            "type": entity.get("type"),
        },
        "total_value": total_value,
        "total_cost_basis": total_cost,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "holdings": holdings_with_pnl,
    }


@app.get("/api/fund/{fund_id}/activity")
def get_fund_activity(fund_id: str):
    """Get recent activity for a fund."""
    raw_transfers = arkham.get_transfers(fund_id, limit=50)
    activity = arkham.parse_transfers(raw_transfers, fund_id)
    return {"activity": activity}


@app.get("/api/fund/{fund_id}/flows")
def get_fund_flows(fund_id: str):
    """Get flow data for charts."""
    raw_flows = arkham.get_flows(fund_id)

    # Simplify for frontend
    flows = {}
    for chain, data in raw_flows.items():
        if isinstance(data, list) and data:
            # Get last 60 data points
            recent = data[-60:]
            flows[chain] = {
                "total_inflow": recent[-1].get("cumulativeInflow", 0) if recent else 0,
                "total_outflow": recent[-1].get("cumulativeOutflow", 0) if recent else 0,
                "points": [
                    {
                        "time": p.get("time"),
                        "inflow": p.get("cumulativeInflow", 0),
                        "outflow": p.get("cumulativeOutflow", 0),
                    }
                    for p in recent
                ],
            }

    return {"flows": flows}


@app.get("/api/compare")
def compare_funds():
    """Compare all funds."""
    results = []

    for fund_id in arkham.FUNDS:
        try:
            entity = arkham.get_entity(fund_id)
            if not entity:
                continue

            raw_portfolio = arkham.get_portfolio(fund_id)
            holdings = arkham.parse_portfolio(raw_portfolio)
            total_value = sum(h["value_usd"] for h in holdings)

            results.append({
                "id": fund_id,
                "name": entity.get("name", fund_id),
                "total_value": total_value,
                "holdings_count": len(holdings),
                "top_holdings": [
                    {"symbol": h["symbol"], "value": h["value_usd"]}
                    for h in holdings[:5]
                ],
            })
        except Exception as e:
            print(f"Error comparing {fund_id}: {e}")

    results.sort(key=lambda x: x["total_value"], reverse=True)
    return {"funds": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
