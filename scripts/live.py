"""
live.py — CLI entry point for live / paper trading.

Usage:
    python scripts/live.py --paper                # paper trading
    python scripts/live.py --paper --symbol AAPL  # specific symbol
    python scripts/live.py --live                  # LIVE (use with caution!)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.engine import TradingEngine
from src.live.alpaca_adapter import AlpacaAdapter
from src.live.feed import AlpacaBarFeed
from src.models import Candle


async def run_live(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(name)-20s  %(levelname)-7s  %(message)s",
    )
    log = logging.getLogger("live")

    cfg = load_config(args.config)
    paper = not args.live

    # Connect broker
    broker = AlpacaAdapter(paper=paper)
    await broker.connect()

    acct = await broker.get_account()
    log.info("Account equity: $%s", acct.get("equity", "?"))

    # Create engine
    engine = TradingEngine(cfg)

    # Set up feed
    feed = AlpacaBarFeed(
        symbol=args.symbol or cfg.live.symbol,
        primary_tf=cfg.vectors.primary_timeframe,
        poll_interval_seconds=30,
        paper=paper,
    )

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _stop():
        log.info("Shutting down...")
        feed.stop()
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    def on_bar(candle: Candle) -> None:
        event = engine.on_bar(candle)

        if event.signal:
            log.info("SIGNAL: %s", event.signal.reason)

        if event.trade_result:
            log.info(
                "TRADE CLOSED: %s  pnl=$%.2f",
                event.trade_result.exit_reason,
                event.trade_result.net_pnl,
            )

        log.info(
            "Bar %s  equity=$%.2f  pos_pnl=$%.2f",
            candle.timestamp.strftime("%H:%M"),
            event.equity,
            event.position_pnl,
        )

    # Start feed (this blocks until stopped)
    try:
        await feed.stream(on_bar)
    except KeyboardInterrupt:
        pass
    finally:
        await broker.disconnect()
        log.info("Live session ended")


def main() -> None:
    parser = argparse.ArgumentParser(description="Brinks Box Live Trading")
    parser.add_argument("--config", default=None, help="Path to YAML config")
    parser.add_argument("--symbol", default=None, help="Symbol to trade")
    parser.add_argument("--paper", action="store_true", help="Paper trading mode")
    parser.add_argument("--live", action="store_true", help="LIVE trading (use caution)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not args.paper and not args.live:
        args.paper = True  # Default to paper

    asyncio.run(run_live(args))


if __name__ == "__main__":
    main()
