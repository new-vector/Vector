"""Tests for brinks_box.py — Box building, Asian range, internal vectors."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.brinks_box import BrinksBoxBuilder
from src.config import SessionConfig
from src.models import Candle, Direction, VectorCandle, VectorSource
from src.session import SessionManager

ET = ZoneInfo("America/New_York")


def _candle(hour, minute, o, h, l, c, vol=100):
    return Candle(
        timestamp=datetime(2024, 6, 12, hour, minute, tzinfo=ET),
        open=o, high=h, low=l, close=c, volume=vol,
    )


@pytest.fixture
def builder():
    cfg = SessionConfig()
    sm = SessionManager(cfg)
    return BrinksBoxBuilder(sm)


class TestBrinksBoxBuilder:
    def test_box_forms_after_brinks_session(self, builder):
        """Box should be ready after 10:00 with correct high/low/mid."""
        # Warm up Asian session (00:00 - 08:00)
        builder.on_bar(_candle(3, 0, 400, 402, 398, 401))
        builder.on_bar(_candle(7, 55, 401, 403, 399, 400))

        # Brinks session bars
        builder.on_bar(_candle(9, 0, 100, 105, 98, 103))
        builder.on_bar(_candle(9, 5, 103, 107, 101, 106))
        builder.on_bar(_candle(9, 55, 106, 108, 104, 105))

        assert not builder.is_box_ready

        # End of Brinks
        builder.on_bar(_candle(10, 0, 105, 106, 103, 104))

        assert builder.is_box_ready
        assert builder.box.session_high == 108
        assert builder.box.session_low == 98
        assert builder.box.mid == (108 + 98) / 2

    def test_box_resets_on_new_session(self, builder):
        # Day 1 Brinks
        builder.on_bar(_candle(9, 0, 100, 110, 90, 105))
        builder.on_bar(_candle(10, 0, 105, 106, 103, 104))
        assert builder.box.session_high == 110

        # Simulate next day — new Brinks start
        next_day = Candle(
            timestamp=datetime(2024, 6, 13, 9, 0, tzinfo=ET),
            open=200, high=205, low=198, close=203, volume=100,
        )
        builder.on_bar(next_day)
        assert builder.box.session_high == 205  # reset to new day

    def test_internal_vectors_tracked(self, builder):
        builder.on_bar(_candle(9, 0, 100, 105, 98, 103))

        vec = VectorCandle(
            direction=Direction.BEAR,
            high=105, low=98,
            body_high=103, body_low=100,
            bar_index=1,
            timestamp=datetime(2024, 6, 12, 9, 5, tzinfo=ET),
        )
        builder.add_internal_vector(vec)

        assert len(builder.box.internal_bear_vectors) == 1
        assert len(builder.box.unrecovered_internal_bear_vectors) == 1

    def test_asian_range_set(self, builder):
        builder.on_bar(_candle(3, 0, 400, 410, 395, 405))
        builder.on_bar(_candle(7, 55, 405, 412, 398, 408))

        # Trigger Asian end + Brinks start
        builder.on_bar(_candle(9, 0, 100, 105, 98, 103))

        assert builder.box.asian_session_high == 412
        assert builder.box.asian_session_low == 395

    def test_asian_sweep_detection(self, builder):
        # Asian range 395-412
        builder.on_bar(_candle(3, 0, 400, 412, 395, 405))

        # Trigger Brinks, then sweep Asian high
        builder.on_bar(_candle(9, 0, 410, 415, 408, 413))
        builder.on_bar(_candle(10, 0, 413, 414, 411, 412))

        assert builder.box.asian_range_swept_high is True
