"""
session.py — Timezone-aware session window detection.

Detects Brinks Box session, trade window, Asian session, and their
transitions (started / ended) using ``zoneinfo``.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.config import SessionConfig


# ── Session Window ───────────────────────────────────────────────────────

class SessionWindow:
    """
    Represents a named intraday window (e.g. Brinks 09:00-10:00 ET).
    Provides ``is_active(ts)`` and transition helpers.
    """

    def __init__(self, name: str, start: str, end: str, tz: ZoneInfo) -> None:
        self.name = name
        self._start = _parse_time(start)
        self._end = _parse_time(end)
        self._tz = tz
        self._prev_active: bool = False

    def is_active(self, ts: datetime) -> bool:
        """Return True if *ts* falls within the session window."""
        local = ts.astimezone(self._tz)
        t = local.time()
        if self._start <= self._end:
            return self._start <= t < self._end
        # Wraps midnight
        return t >= self._start or t < self._end

    def check_transition(self, ts: datetime) -> tuple[bool, bool]:
        """
        Return (session_started, session_ended) relative to the
        previous call.  Must be called once per bar in order.
        """
        active = self.is_active(ts)
        started = active and not self._prev_active
        ended = not active and self._prev_active
        self._prev_active = active
        return started, ended

    def reset(self) -> None:
        self._prev_active = False


# ── Session Manager ──────────────────────────────────────────────────────

class SessionManager:
    """
    Orchestrates all session windows for a single trading day.

    Attributes
    ----------
    brinks : SessionWindow
    trade_window : SessionWindow
    asian : SessionWindow
    """

    def __init__(self, cfg: SessionConfig) -> None:
        self._tz = ZoneInfo(cfg.timezone)
        self._weekdays_only = cfg.weekdays_only

        self.brinks = SessionWindow("brinks", cfg.brinks_start, cfg.brinks_end, self._tz)
        self.trade_window = SessionWindow("trade_window", cfg.trade_window_start, cfg.trade_window_end, self._tz)
        self.asian = SessionWindow("asian", cfg.asian_session_start, cfg.asian_session_end, self._tz)

        self._current_day_id: int = -1

    # ── Per-bar interface ────────────────────────────────────────────

    def is_weekday(self, ts: datetime) -> bool:
        local = ts.astimezone(self._tz)
        return local.weekday() < 5  # Mon=0 … Fri=4

    def can_trade(self, ts: datetime) -> bool:
        if self._weekdays_only and not self.is_weekday(ts):
            return False
        return True

    def day_id(self, ts: datetime) -> int:
        """Unique integer per calendar day in the session timezone."""
        local = ts.astimezone(self._tz)
        return local.year * 10_000 + local.month * 100 + local.day

    def is_new_day(self, ts: datetime) -> bool:
        d = self.day_id(ts)
        if d != self._current_day_id:
            self._current_day_id = d
            return True
        return False

    @property
    def tz(self) -> ZoneInfo:
        return self._tz


# ── helpers ──────────────────────────────────────────────────────────────

def _parse_time(s: str) -> time:
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))
