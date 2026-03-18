"""
backtest.py — CLI entry point for running backtests.

Usage:
    python scripts/backtest.py                           # uses default.yaml + sample data
    python scripts/backtest.py --data data/spy_5m.csv
    python scripts/backtest.py --config config/aggressive.yaml
    python scripts/backtest.py --symbol SPY --start 2024-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.data_loader import load_csv, load_alpaca, merge_multi_timeframe
from src.backtest.runner import BacktestRunner
from src.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Brinks Box Backtest")
    parser.add_argument("--config", default=None, help="Path to YAML config")
    parser.add_argument("--data", default=None, help="Path to CSV data file")
    parser.add_argument("--symbol", default="SPY", help="Symbol to backtest")
    parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--timeframe", default="5m", help="Primary timeframe")
    parser.add_argument("--news-calendar", default=None, help="Path to news calendar CSV")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(name)-20s  %(levelname)-7s  %(message)s",
    )

    cfg = load_config(args.config)

    # Load data
    if args.data:
        bars = load_csv(args.data, timeframe=args.timeframe)
    elif args.start and args.end:
        start = datetime.fromisoformat(args.start)
        end = datetime.fromisoformat(args.end)
        bars = load_alpaca(args.symbol, start, end, timeframe=args.timeframe)
    else:
        print("Provide --data <csv> or --start/--end for Alpaca data.")
        print("Example: python scripts/backtest.py --data data/spy_5m.csv")
        sys.exit(1)

    if not bars:
        print("No bars loaded.")
        sys.exit(1)

    runner = BacktestRunner(cfg)

    if args.news_calendar:
        runner.load_news_calendar(args.news_calendar)

    report = runner.run(bars)
    report.print_summary()


if __name__ == "__main__":
    main()
