"""
runner.py — Event-driven backtester.

Feeds a chronological bar stream through the ``TradingEngine`` and
collects results.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Sequence

from src.backtest.analytics import BacktestReport, compute_analytics
from src.config import SystemConfig, load_config
from src.engine import TradingEngine
from src.models import Candle

log = logging.getLogger(__name__)


class BacktestRunner:
    """
    Run a backtest using a pre-loaded bar stream.

    Usage::

        cfg = load_config()
        runner = BacktestRunner(cfg)
        report = runner.run(candles)
        report.print_summary()
    """

    def __init__(self, cfg: SystemConfig) -> None:
        self.cfg = cfg
        self.engine = TradingEngine(cfg)

    def run(self, bars: Sequence[Candle]) -> BacktestReport:
        """
        Feed *bars* through the engine and return a full performance report.
        """
        log.info("Starting backtest: %d bars", len(bars))
        t0 = time.perf_counter()

        for candle in bars:
            self.engine.on_bar(candle)

        elapsed = time.perf_counter() - t0
        log.info(
            "Backtest complete: %d bars in %.2fs  (%d trades)",
            len(bars),
            elapsed,
            len(self.engine.trade_journal),
        )

        return compute_analytics(
            trades=self.engine.trade_journal,
            equity_curve=self.engine.portfolio.equity_curve,
            initial_capital=self.cfg.backtest.initial_capital,
            min_trades_wanted=self.cfg.backtest.min_trades_wanted,
            elapsed_seconds=elapsed,
        )

    def load_news_calendar(self, path: str | Path) -> None:
        """Optionally load a news calendar CSV before running."""
        self.engine.news_filter.load_csv(path)
