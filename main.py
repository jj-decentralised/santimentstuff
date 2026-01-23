"""Entry point for Fund Portfolio Tracker."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "products.fund_tracker.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
