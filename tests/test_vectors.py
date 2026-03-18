"""Tests for vectors.py — Tick-proxy scoring and recovery tracking."""

from datetime import datetime, timezone

import pytest

from src.models import Candle, Direction, VectorCandle, VectorSource, VectorStrength
from src.config import VectorConfig
from src.vectors import TimeframeVectorTracker, VectorEngine, compute_tick_proxy_score


@pytest.fixture
def cfg():
    return VectorConfig(lookback=5, primary_threshold=2.0, secondary_threshold=1.5)


def _candle(idx, o, h, l, c, vol, tf="5m"):
    return Candle(
        timestamp=datetime(2024, 6, 10, 9, idx, tzinfo=timezone.utc),
        open=o, high=h, low=l, close=c, volume=vol,
        bar_index=idx, timeframe=tf,
    )


# ── Tick-proxy score ─────────────────────────────────────────

class TestTickProxyScore:
    def test_high_score_on_extreme_candle(self):
        candle = _candle(1, 100.0, 103.0, 99.0, 102.5, 5000)
        score = compute_tick_proxy_score(candle, volume_z=3.0, range_z=3.0)
        assert score > 2.0

    def test_low_score_on_normal_candle(self):
        candle = _candle(1, 100.0, 100.5, 99.8, 100.2, 100)
        score = compute_tick_proxy_score(candle, volume_z=0.1, range_z=0.1)
        assert score < 1.0

    def test_body_fraction_boost(self):
        # High body fraction (close to 1.0) should boost score
        full_body = _candle(1, 100.0, 102.0, 100.0, 102.0, 100)
        tiny_body = _candle(1, 101.0, 102.0, 100.0, 101.1, 100)
        s1 = compute_tick_proxy_score(full_body, 1.0, 1.0)
        s2 = compute_tick_proxy_score(tiny_body, 1.0, 1.0)
        assert s1 > s2


# ── Vector detection ─────────────────────────────────────────

class TestTimeframeVectorTracker:
    def test_detects_bull_vector(self, cfg):
        tracker = TimeframeVectorTracker("5m", cfg)

        # Feed enough normal bars to build rolling stats
        for i in range(cfg.lookback):
            c = _candle(i, 100.0, 100.5, 99.5, 100.2, 100)
            tracker.process_bar(c, is_brinks_session=False)

        # Now feed a high-volume bullish candle
        big = _candle(cfg.lookback, 100.0, 104.0, 99.5, 103.5, 1000)
        vec = tracker.process_bar(big, is_brinks_session=False)

        assert vec is not None
        assert vec.direction == Direction.BULL
        assert vec.source == VectorSource.EXTERNAL

    def test_detects_bear_vector(self, cfg):
        tracker = TimeframeVectorTracker("5m", cfg)

        for i in range(cfg.lookback):
            c = _candle(i, 100.0, 100.5, 99.5, 100.2, 100)
            tracker.process_bar(c, is_brinks_session=False)

        big = _candle(cfg.lookback, 103.0, 103.5, 99.5, 100.0, 1000)
        vec = tracker.process_bar(big, is_brinks_session=False)

        assert vec is not None
        assert vec.direction == Direction.BEAR

    def test_internal_vector_classification(self, cfg):
        tracker = TimeframeVectorTracker("5m", cfg)

        for i in range(cfg.lookback):
            c = _candle(i, 100.0, 100.5, 99.5, 100.2, 100)
            tracker.process_bar(c, is_brinks_session=True)

        big = _candle(cfg.lookback, 100.0, 104.0, 99.5, 103.5, 1000)
        vec = tracker.process_bar(big, is_brinks_session=True)

        assert vec is not None
        assert vec.source == VectorSource.INTERNAL

    def test_no_vector_on_low_volume(self, cfg):
        tracker = TimeframeVectorTracker("5m", cfg)

        for i in range(cfg.lookback):
            c = _candle(i, 100.0, 100.5, 99.5, 100.2, 100)
            tracker.process_bar(c, is_brinks_session=False)

        # Normal volume
        normal = _candle(cfg.lookback, 100.0, 101.0, 99.5, 100.8, 105)
        vec = tracker.process_bar(normal, is_brinks_session=False)
        assert vec is None

    def test_no_vector_on_doji(self, cfg):
        """High volume but tiny body → not a vector."""
        tracker = TimeframeVectorTracker("5m", cfg)

        for i in range(cfg.lookback):
            c = _candle(i, 100.0, 100.5, 99.5, 100.2, 100)
            tracker.process_bar(c, is_brinks_session=False)

        doji = _candle(cfg.lookback, 101.0, 103.0, 99.0, 101.1, 1000)
        vec = tracker.process_bar(doji, is_brinks_session=False)
        # Body fraction = 0.1/4.0 = 0.025 → below min
        assert vec is None


# ── Recovery tracking ────────────────────────────────────────

class TestVectorRecovery:
    def test_bear_vector_full_recovery(self):
        vec = VectorCandle(
            direction=Direction.BEAR,
            high=105.0, low=100.0,
            body_high=104.5, body_low=100.5,
            bar_index=10,
            timestamp=datetime(2024, 6, 10, 9, 0, tzinfo=timezone.utc),
        )

        # Price trades up through the full range
        vec.update_recovery(candle_high=102.0, candle_low=99.0)
        assert vec.is_partially_recovered is True
        assert vec.is_fully_recovered is False

        vec.update_recovery(candle_high=105.0, candle_low=101.0)
        assert vec.is_fully_recovered is True

    def test_bull_vector_full_recovery(self):
        vec = VectorCandle(
            direction=Direction.BULL,
            high=105.0, low=100.0,
            body_high=104.5, body_low=100.5,
            bar_index=10,
            timestamp=datetime(2024, 6, 10, 9, 0, tzinfo=timezone.utc),
        )

        # Price trades down through the full range
        vec.update_recovery(candle_high=106.0, candle_low=102.0)
        assert vec.is_partially_recovered is True
        assert vec.is_fully_recovered is False

        vec.update_recovery(candle_high=103.0, candle_low=100.0)
        assert vec.is_fully_recovered is True

    def test_partial_recovery_pct(self):
        vec = VectorCandle(
            direction=Direction.BEAR,
            high=110.0, low=100.0,
            body_high=109.0, body_low=101.0,
            bar_index=10,
            timestamp=datetime(2024, 6, 10, 9, 0, tzinfo=timezone.utc),
        )

        vec.update_recovery(candle_high=105.0, candle_low=99.0)
        assert 0.4 < vec.recovery_pct < 0.6  # ~50% recovered

    def test_no_recovery_when_price_doesnt_enter(self):
        vec = VectorCandle(
            direction=Direction.BEAR,
            high=110.0, low=105.0,
            body_high=109.0, body_low=106.0,
            bar_index=10,
            timestamp=datetime(2024, 6, 10, 9, 0, tzinfo=timezone.utc),
        )

        vec.update_recovery(candle_high=104.0, candle_low=100.0)
        assert vec.is_partially_recovered is False
        assert vec.is_fully_recovered is False


# ── Multi-TF confluence ──────────────────────────────────────

class TestMultiTimeframeEngine:
    def test_separate_timeframe_tracking(self, cfg):
        cfg.timeframes = ["5m", "15m"]
        engine = VectorEngine(cfg)

        # Feed 5m bars
        for i in range(cfg.lookback):
            c = _candle(i, 100.0, 100.5, 99.5, 100.2, 100, tf="5m")
            engine.process_bar(c, is_brinks_session=False)

        # Feed 15m bars
        for i in range(cfg.lookback):
            c = _candle(i, 100.0, 100.5, 99.5, 100.2, 100, tf="15m")
            engine.process_bar(c, is_brinks_session=False)

        assert "5m" in engine.trackers
        assert "15m" in engine.trackers
