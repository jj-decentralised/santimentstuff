"""
Smart Money Dashboard

Entry point for the application.
"""

import uvicorn

from products.smart_money.api import app


if __name__ == "__main__":
    uvicorn.run(
        "products.smart_money.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
