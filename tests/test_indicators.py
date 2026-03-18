"""Tests for indicators.py — EMA, ATR, SMA, ZScoreTracker."""

import math
import pytest

from src.indicators import ATR, EMA, SMA, RollingStd, ZScoreTracker


class TestEMA:
    def test_first_value_equals_input(self):
        ema = EMA(10)
        assert ema.update(50.0) == 50.0

    def test_converges_to_constant(self):
        ema = EMA(5)
        for _ in range(100):
            ema.update(42.0)
        assert abs(ema.value - 42.0) < 1e-10

    def test_reacts_to_step_change(self):
        ema = EMA(5)
        for _ in range(20):
            ema.update(100.0)
        ema.update(200.0)
        # Should have moved toward 200 but not reached it
        assert 100.0 < ema.value < 200.0

    def test_ready_after_period(self):
        ema = EMA(10)
        for i in range(9):
            ema.update(float(i))
            assert ema.ready is False
        ema.update(9.0)
        assert ema.ready is True


class TestSMA:
    def test_simple_average(self):
        sma = SMA(3)
        sma.update(1.0)
        sma.update(2.0)
        sma.update(3.0)
        assert abs(sma.value - 2.0) < 1e-10

    def test_rolling_window(self):
        sma = SMA(3)
        sma.update(1.0)
        sma.update(2.0)
        sma.update(3.0)
        sma.update(6.0)  # drops the 1.0
        assert abs(sma.value - (2 + 3 + 6) / 3) < 1e-10


class TestATR:
    def test_single_bar(self):
        atr = ATR(14)
        val = atr.update(high=105, low=100, close=103)
        assert abs(val - 5.0) < 1e-10  # first bar: high - low

    def test_atr_positive(self):
        atr = ATR(3)
        for i in range(10):
            atr.update(100 + i, 98 + i, 99 + i)
        assert atr.value > 0


class TestZScoreTracker:
    def test_zero_zscore_on_constant(self):
        z = ZScoreTracker(period=5)
        for _ in range(10):
            z.update(100.0)
        assert abs(z.value) < 1e-6

    def test_positive_zscore_on_spike(self):
        z = ZScoreTracker(period=5)
        for _ in range(5):
            z.update(100.0)
        z.update(200.0)
        assert z.value > 1.0
