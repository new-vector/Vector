"""Tests for backtest runner and analytics."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.backtest.runner import BacktestRunner
from src.config import load_config
from src.models import Candle

ET = ZoneInfo("America/New_York")


def _generate_synthetic_bars(days=5):
    """Generate synthetic 5m bars over multiple days with volume spikes."""
    bars = []
    bar_idx = 0
    for day in range(10, 10 + days):
        # Asian session (00:00 - 08:00) — flat
        for hour in range(0, 8):
            for minute in range(0, 60, 5):
                bar_idx += 1
                bars.append(Candle(
                    timestamp=datetime(2024, 6, day, hour, minute, tzinfo=ET),
                    open=500, high=501, low=499, close=500, volume=50,
                    bar_index=bar_idx, timeframe="5m",
                ))

        # Pre-Brinks (08:00-09:00)
        for minute in range(0, 60, 5):
            bar_idx += 1
            bars.append(Candle(
                timestamp=datetime(2024, 6, day, 8, minute, tzinfo=ET),
                open=500, high=502, low=498, close=501, volume=80,
                bar_index=bar_idx, timeframe="5m",
            ))

        # Brinks session (09:00-10:00) — create a range
        for minute in range(0, 60, 5):
            bar_idx += 1
            # Gradually push price up then down to create a box
            drift = minute * 0.2
            bars.append(Candle(
                timestamp=datetime(2024, 6, day, 9, minute, tzinfo=ET),
                open=500 + drift, high=502 + drift, low=498 + drift,
                close=501 + drift, volume=150,
                bar_index=bar_idx, timeframe="5m",
            ))

        # Trade window (10:00-12:00) — trending up
        for minute in range(0, 120, 5):
            bar_idx += 1
            base = 512 + minute * 0.1
            bars.append(Candle(
                timestamp=datetime(2024, 6, day, 10, minute, tzinfo=ET),
                open=base, high=base + 2, low=base - 1, close=base + 1.5,
                volume=200,
                bar_index=bar_idx, timeframe="5m",
            ))

        # Post-window (12:00-16:00)
        for hour in range(12, 16):
            for minute in range(0, 60, 5):
                bar_idx += 1
                bars.append(Candle(
                    timestamp=datetime(2024, 6, day, hour, minute, tzinfo=ET),
                    open=530, high=531, low=529, close=530, volume=50,
                    bar_index=bar_idx, timeframe="5m",
                ))

    return bars


class TestBacktestRunner:
    def test_runner_completes_without_error(self):
        cfg = load_config(overrides={
            "trade_logic": {"use_ema_filter": False, "require_mid_hold": False},
            "vectors": {"lookback": 5, "timeframes": ["5m"]},
            "backtest": {"min_trades_wanted": 1},
        })
        runner = BacktestRunner(cfg)
        bars = _generate_synthetic_bars(days=3)
        report = runner.run(bars)

        assert report.total_trades >= 0
        assert report.elapsed_seconds > 0

    def test_report_metrics_valid(self):
        cfg = load_config(overrides={
            "trade_logic": {"use_ema_filter": False, "require_mid_hold": False},
            "vectors": {"lookback": 5, "timeframes": ["5m"]},
        })
        runner = BacktestRunner(cfg)
        bars = _generate_synthetic_bars(days=5)
        report = runner.run(bars)

        # Win rate should be between 0 and 1
        assert 0.0 <= report.win_rate <= 1.0
        # Total commission should be non-negative
        assert report.total_commission >= 0
        # Max drawdown should be non-negative
        assert report.max_drawdown >= 0
