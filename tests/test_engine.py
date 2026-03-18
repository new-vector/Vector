"""Tests for engine.py — Full integration test."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.config import SystemConfig, load_config
from src.engine import TradingEngine
from src.models import Candle

ET = ZoneInfo("America/New_York")


def _candle(day, hour, minute, o, h, l, c, vol=100):
    return Candle(
        timestamp=datetime(2024, 6, day, hour, minute, tzinfo=ET),
        open=o, high=h, low=l, close=c, volume=vol,
        timeframe="5m",
    )


@pytest.fixture
def cfg():
    return load_config(overrides={
        "trade_logic": {
            "use_ema_filter": False,
            "require_mid_hold": False,
        },
        "risk": {
            "stop_mode": "opposite_box_side",
            "one_trade_per_day": True,
        },
        "vectors": {
            "lookback": 5,
            "timeframes": ["5m"],
        },
    })


class TestTradingEngine:
    def test_engine_processes_bars_without_crash(self, cfg):
        engine = TradingEngine(cfg)

        # Feed a day of bars
        for minute in range(0, 60, 5):
            engine.on_bar(_candle(10, 9, minute, 500, 505, 495, 502))
        for minute in range(0, 120, 5):
            engine.on_bar(_candle(10, 10, minute, 502, 510, 498, 508))

        assert engine.total_bars > 0

    def test_box_forms_after_session(self, cfg):
        engine = TradingEngine(cfg)

        # Brinks session bars
        engine.on_bar(_candle(10, 9, 0, 500, 510, 490, 505, vol=100))
        engine.on_bar(_candle(10, 9, 30, 505, 515, 495, 510, vol=100))
        engine.on_bar(_candle(10, 9, 55, 510, 512, 502, 508, vol=100))

        assert not engine.box_builder.is_box_ready

        # End of Brinks
        engine.on_bar(_candle(10, 10, 0, 508, 509, 505, 507, vol=100))

        assert engine.box_builder.is_box_ready
        assert engine.box_builder.box.session_high == 515
        assert engine.box_builder.box.session_low == 490

    def test_no_crash_on_empty_bars(self, cfg):
        engine = TradingEngine(cfg)
        event = engine.on_bar(_candle(10, 12, 0, 100, 101, 99, 100))
        assert event is not None
        assert event.equity > 0

    def test_daily_trade_limit_enforced(self, cfg):
        """After one trade, no more signals should fire that day."""
        engine = TradingEngine(cfg)

        # Warm up indicators
        for i in range(25):
            engine.on_bar(_candle(10, 3, i * 2, 500, 502, 498, 501, vol=100))

        # Form box
        engine.on_bar(_candle(10, 9, 0, 500, 520, 480, 510, vol=100))
        engine.on_bar(_candle(10, 10, 0, 510, 511, 509, 510, vol=100))

        # Count signals fired during trade window
        signals_fired = 0
        for minute in range(5, 120, 5):
            event = engine.on_bar(_candle(10, 10, minute, 522, 530, 520, 528, vol=2000))
            if event.signal is not None:
                signals_fired += 1

        # Should fire at most 1 trade due to daily limit
        assert signals_fired <= 1
