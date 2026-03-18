"""Tests for risk.py — Stop/target calculation and position sizing."""

import math
from datetime import datetime, timezone

import pytest

from src.config import RiskConfig
from src.indicators import ATR
from src.models import (
    BrinksBox,
    Direction,
    Signal,
    SignalType,
    VectorCandle,
)
from src.risk import RiskManager


@pytest.fixture
def box():
    b = BrinksBox()
    b.session_high = 510.0
    b.session_low = 490.0
    b.mid = 500.0
    b.is_ready = True
    return b


@pytest.fixture
def atr():
    a = ATR(14)
    # Seed ATR with some bars
    for i in range(20):
        a.update(102 + i * 0.1, 98 + i * 0.1, 100 + i * 0.1)
    return a


class TestRiskManager:
    def test_opposite_box_side_stop_long(self, box, atr):
        cfg = RiskConfig(stop_mode="opposite_box_side", buffer_ticks=2)
        rm = RiskManager(cfg, atr, tick_size=0.01)

        sig = Signal(
            signal_type=SignalType.REVERSAL_LONG,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bar_index=100,
            price=505.0,
        )

        params = rm.compute(sig, box, entry_price=505.0, equity=10000)
        assert params is not None
        assert params.stop_price == 490.0 - 0.02  # box low - buffer
        assert params.target_price > 505.0

    def test_opposite_box_side_stop_short(self, box, atr):
        cfg = RiskConfig(stop_mode="opposite_box_side", buffer_ticks=2)
        rm = RiskManager(cfg, atr, tick_size=0.01)

        sig = Signal(
            signal_type=SignalType.CONTINUATION_SHORT,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bar_index=100,
            price=488.0,
        )

        params = rm.compute(sig, box, entry_price=488.0, equity=10000)
        assert params is not None
        assert params.stop_price == 510.0 + 0.02  # box high + buffer
        assert params.target_price < 488.0

    def test_box_mid_stop(self, box, atr):
        cfg = RiskConfig(stop_mode="box_mid", buffer_ticks=0)
        rm = RiskManager(cfg, atr)

        sig = Signal(
            signal_type=SignalType.REVERSAL_LONG,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bar_index=100,
            price=505.0,
        )

        params = rm.compute(sig, box, entry_price=505.0, equity=10000)
        assert params is not None
        assert params.stop_price == 500.0

    def test_vector_target_used(self, box, atr):
        cfg = RiskConfig(stop_mode="opposite_box_side")
        rm = RiskManager(cfg, atr)

        target_vec = VectorCandle(
            direction=Direction.BEAR,
            high=525.0, low=520.0,
            body_high=524.0, body_low=521.0,
            bar_index=50,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        sig = Signal(
            signal_type=SignalType.REVERSAL_LONG,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bar_index=100,
            price=505.0,
            target_vector=target_vec,
        )

        params = rm.compute(sig, box, entry_price=505.0, equity=10000)
        assert params is not None
        assert params.target_price == 521.0  # body_low of bear vec above

    def test_fallback_rr_target(self, box, atr):
        cfg = RiskConfig(stop_mode="opposite_box_side", rr_target=2.0)
        rm = RiskManager(cfg, atr)

        sig = Signal(
            signal_type=SignalType.REVERSAL_LONG,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bar_index=100,
            price=505.0,
        )

        params = rm.compute(sig, box, entry_price=505.0, equity=10000)
        assert params is not None
        risk = 505.0 - (490.0 - 0.01 * 2)  # entry - (box low - buffer)
        expected_target = 505.0 + risk * 2.0
        assert abs(params.target_price - expected_target) < 0.1

    def test_rejects_invalid_geometry(self, box, atr):
        """If stop is on wrong side of entry, should return None."""
        cfg = RiskConfig(stop_mode="opposite_box_side")
        rm = RiskManager(cfg, atr)

        # Long entry BELOW the box low → stop would be above entry
        sig = Signal(
            signal_type=SignalType.REVERSAL_LONG,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            bar_index=100,
            price=485.0,
        )

        params = rm.compute(sig, box, entry_price=485.0, equity=10000)
        # Stop at 490 > entry at 485 → invalid
        assert params is None
