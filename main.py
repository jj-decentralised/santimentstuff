"""
Santiment Platform - Main Entry Point

Run individual product APIs or the unified Research Terminal.

Usage:
    # Run the unified Research Terminal (recommended)
    python main.py terminal

    # Run individual products
    python main.py health      # Health Score API
    python main.py whale       # Whale Watch API
    python main.py sentiment   # Sentiment Bot API
    python main.py narrative   # Narrative AI API

    # Run all products on different ports
    python main.py all
"""

import argparse
import asyncio
import sys

import uvicorn


def run_terminal(host: str = "0.0.0.0", port: int = 8000):
    """Run the unified Research Terminal API."""
    from products.research_terminal.api import app
    uvicorn.run(app, host=host, port=port)


def run_health(host: str = "0.0.0.0", port: int = 8001):
    """Run the Health Score API."""
    from products.health_score.api import app
    uvicorn.run(app, host=host, port=port)


def run_whale(host: str = "0.0.0.0", port: int = 8002):
    """Run the Whale Watch API."""
    from products.whale_watch.api import app
    uvicorn.run(app, host=host, port=port)


def run_sentiment(host: str = "0.0.0.0", port: int = 8003):
    """Run the Sentiment Bot API."""
    from products.sentiment_bot.api import app
    uvicorn.run(app, host=host, port=port)


def run_narrative(host: str = "0.0.0.0", port: int = 8004):
    """Run the Narrative AI API."""
    from products.narrative_ai.api import app
    uvicorn.run(app, host=host, port=port)


def run_all():
    """Run all APIs on different ports."""
    import multiprocessing

    processes = [
        multiprocessing.Process(target=run_terminal, kwargs={"port": 8000}),
        multiprocessing.Process(target=run_health, kwargs={"port": 8001}),
        multiprocessing.Process(target=run_whale, kwargs={"port": 8002}),
        multiprocessing.Process(target=run_sentiment, kwargs={"port": 8003}),
        multiprocessing.Process(target=run_narrative, kwargs={"port": 8004}),
    ]

    print("Starting all APIs...")
    print("  - Research Terminal: http://localhost:8000")
    print("  - Health Score:      http://localhost:8001")
    print("  - Whale Watch:       http://localhost:8002")
    print("  - Sentiment Bot:     http://localhost:8003")
    print("  - Narrative AI:      http://localhost:8004")
    print()

    for p in processes:
        p.start()

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\nShutting down...")
        for p in processes:
            p.terminate()


def main():
    parser = argparse.ArgumentParser(
        description="Santiment Platform - Crypto Research & Analysis APIs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Products:
  terminal   - Unified Research Terminal (recommended, port 8000)
  health     - Project Health Score API (port 8001)
  whale      - Whale Watching Dashboard API (port 8002)
  sentiment  - Social Sentiment Trading Bot API (port 8003)
  narrative  - AI Market Narrative Analyzer API (port 8004)
  all        - Run all products simultaneously

Examples:
  python main.py terminal           # Start Research Terminal
  python main.py terminal --port 3000  # Custom port
  python main.py all                # Start all products
        """
    )

    parser.add_argument(
        "product",
        choices=["terminal", "health", "whale", "sentiment", "narrative", "all"],
        help="Product to run"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to run on (default varies by product)"
    )

    args = parser.parse_args()

    if args.product == "all":
        run_all()
    else:
        runners = {
            "terminal": (run_terminal, 8000),
            "health": (run_health, 8001),
            "whale": (run_whale, 8002),
            "sentiment": (run_sentiment, 8003),
            "narrative": (run_narrative, 8004),
        }

        runner, default_port = runners[args.product]
        port = args.port or default_port

        print(f"Starting {args.product} API on http://{args.host}:{port}")
        print(f"API docs available at http://{args.host}:{port}/docs")
        print()

        runner(host=args.host, port=port)


if __name__ == "__main__":
    main()
