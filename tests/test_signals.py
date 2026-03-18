"""Tests for signals.py — Entry signal generation with full filter stack."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.brinks_box import BrinksBoxBuilder
from src.config import SessionConfig, TradeLogicConfig, VectorConfig, NewsConfig
from src.indicators import EMA
from src.models import (
    BrinksBox,
    Candle,
    Direction,
    SignalType,
    VectorCandle,
    VectorSource,
)
from src.news import NewsFilter
from src.session import SessionManager
from src.signals import SignalEngine
from src.vectors import VectorEngine

ET = ZoneInfo("America/New_York")


def _candle(hour, minute, o, h, l, c, vol=100):
    return Candle(
        timestamp=datetime(2024, 6, 12, hour, minute, tzinfo=ET),
        open=o, high=h, low=l, close=c, volume=vol,
        bar_index=(hour * 60 + minute),
    )


def _make_engine():
    """Create a fully wired signal engine with a pre-formed box."""
    sess_cfg = SessionConfig()
    trade_cfg = TradeLogicConfig(use_ema_filter=False, require_mid_hold=False)
    vec_cfg = VectorConfig(lookback=5)
    news_cfg = NewsConfig(enabled=False)

    sm = SessionManager(sess_cfg)
    bb = BrinksBoxBuilder(sm)
    ve = VectorEngine(vec_cfg)
    nf = NewsFilter(news_cfg)
    ema_f = EMA(13)
    ema_s = EMA(50)

    # Pre-form the box
    bb.on_bar(_candle(9, 0, 500, 510, 490, 505))
    bb.on_bar(_candle(9, 30, 505, 515, 495, 510))
    bb.on_bar(_candle(9, 55, 510, 512, 502, 508))
    bb.on_bar(_candle(10, 0, 508, 509, 505, 507))  # ends Brinks

    # Add unrecovered internal bear vector
    bear_vec = VectorCandle(
        direction=Direction.BEAR,
        high=510, low=495,
        body_high=508, body_low=497,
        bar_index=2,
        timestamp=datetime(2024, 6, 12, 9, 30, tzinfo=ET),
        source=VectorSource.INTERNAL,
    )
    bb.add_internal_vector(bear_vec)

    engine = SignalEngine(trade_cfg, sm, bb, ve, nf, ema_f, ema_s)
    return engine, bb


class TestSignalEngine:
    def test_reversal_long_fires(self):
        engine, bb = _make_engine()

        # Price closes above the internal bear vector high (510)
        candle = _candle(10, 15, 508, 515, 506, 512)
        sig = engine.evaluate(candle, position_flat=True, trades_today=0, max_trades_per_day=1)

        assert sig is not None
        assert sig.signal_type == SignalType.REVERSAL_LONG

    def test_no_signal_when_position_open(self):
        engine, bb = _make_engine()
        candle = _candle(10, 15, 508, 515, 506, 512)
        sig = engine.evaluate(candle, position_flat=False, trades_today=0, max_trades_per_day=1)
        assert sig is None

    def test_no_signal_when_daily_limit_hit(self):
        engine, bb = _make_engine()
        candle = _candle(10, 15, 508, 515, 506, 512)
        sig = engine.evaluate(candle, position_flat=True, trades_today=1, max_trades_per_day=1)
        assert sig is None

    def test_no_signal_outside_trade_window(self):
        engine, bb = _make_engine()
        # 13:00 is outside the default 10:00-12:00 trade window
        candle = _candle(13, 0, 508, 515, 506, 512)
        sig = engine.evaluate(candle, position_flat=True, trades_today=0, max_trades_per_day=1)
        assert sig is None

    def test_continuation_long_fires(self):
        engine, bb = _make_engine()
        # Clear internal vectors so reversal doesn't fire first
        bb.box.internal_bear_vectors.clear()

        # Price closes above box high (515)
        candle = _candle(10, 20, 514, 520, 513, 518)
        sig = engine.evaluate(candle, position_flat=True, trades_today=0, max_trades_per_day=1)

        assert sig is not None
        assert sig.signal_type == SignalType.CONTINUATION_LONG

    def test_continuation_short_fires(self):
        engine, bb = _make_engine()
        bb.box.internal_bear_vectors.clear()
        bb.box.internal_bull_vectors.clear()

        # Price closes below box low (490)
        candle = _candle(10, 20, 492, 493, 485, 488)
        sig = engine.evaluate(candle, position_flat=True, trades_today=0, max_trades_per_day=1)

        assert sig is not None
        assert sig.signal_type == SignalType.CONTINUATION_SHORT
