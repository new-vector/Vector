"""Tests for session.py — Session detection and transitions."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.config import SessionConfig
from src.session import SessionManager, SessionWindow


ET = ZoneInfo("America/New_York")


@pytest.fixture
def cfg():
    return SessionConfig()


@pytest.fixture
def sm(cfg):
    return SessionManager(cfg)


# ── SessionWindow basics ─────────────────────────────────────

class TestSessionWindow:
    def test_brinks_active_during_session(self):
        w = SessionWindow("brinks", "09:00", "10:00", ET)
        # 09:30 ET on a Wednesday
        ts = datetime(2024, 6, 12, 9, 30, tzinfo=ET)
        assert w.is_active(ts) is True

    def test_brinks_inactive_before_session(self):
        w = SessionWindow("brinks", "09:00", "10:00", ET)
        ts = datetime(2024, 6, 12, 8, 59, tzinfo=ET)
        assert w.is_active(ts) is False

    def test_brinks_inactive_at_end(self):
        w = SessionWindow("brinks", "09:00", "10:00", ET)
        ts = datetime(2024, 6, 12, 10, 0, tzinfo=ET)
        assert w.is_active(ts) is False

    def test_transition_detection(self):
        w = SessionWindow("brinks", "09:00", "10:00", ET)
        t1 = datetime(2024, 6, 12, 8, 55, tzinfo=ET)
        t2 = datetime(2024, 6, 12, 9, 0, tzinfo=ET)
        t3 = datetime(2024, 6, 12, 9, 30, tzinfo=ET)
        t4 = datetime(2024, 6, 12, 10, 0, tzinfo=ET)

        started, ended = w.check_transition(t1)
        assert not started and not ended

        started, ended = w.check_transition(t2)
        assert started and not ended

        started, ended = w.check_transition(t3)
        assert not started and not ended

        started, ended = w.check_transition(t4)
        assert not started and ended

    def test_midnight_wrap(self):
        """Asian session 22:00-08:00 wraps midnight."""
        w = SessionWindow("asian", "22:00", "08:00", ET)
        ts_late = datetime(2024, 6, 12, 23, 0, tzinfo=ET)
        ts_early = datetime(2024, 6, 13, 3, 0, tzinfo=ET)
        ts_out = datetime(2024, 6, 13, 12, 0, tzinfo=ET)

        assert w.is_active(ts_late) is True
        assert w.is_active(ts_early) is True
        assert w.is_active(ts_out) is False


# ── SessionManager ───────────────────────────────────────────

class TestSessionManager:
    def test_weekday_detection(self, sm):
        monday = datetime(2024, 6, 10, 12, 0, tzinfo=ET)
        saturday = datetime(2024, 6, 15, 12, 0, tzinfo=ET)
        assert sm.is_weekday(monday) is True
        assert sm.is_weekday(saturday) is False

    def test_can_trade_blocks_weekend(self, sm):
        sat = datetime(2024, 6, 15, 10, 0, tzinfo=ET)
        assert sm.can_trade(sat) is False

    def test_day_id_unique(self, sm):
        d1 = datetime(2024, 6, 10, 9, 0, tzinfo=ET)
        d2 = datetime(2024, 6, 11, 9, 0, tzinfo=ET)
        assert sm.day_id(d1) != sm.day_id(d2)

    def test_new_day_detection(self, sm):
        d1 = datetime(2024, 6, 10, 9, 0, tzinfo=ET)
        d2 = datetime(2024, 6, 10, 10, 0, tzinfo=ET)
        d3 = datetime(2024, 6, 11, 9, 0, tzinfo=ET)

        assert sm.is_new_day(d1) is True
        assert sm.is_new_day(d2) is False
        assert sm.is_new_day(d3) is True
