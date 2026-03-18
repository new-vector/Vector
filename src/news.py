"""
news.py — Economic calendar integration and news-event filter.

Checks whether a high-impact news event is within the configured
blackout window around a given timestamp.  For backtesting a static
CSV calendar is used; for live trading an async HTTP fetch can be wired.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from src.config import NewsConfig

log = logging.getLogger(__name__)


# ── Data model ───────────────────────────────────────────────────────────

@dataclass(slots=True)
class NewsEvent:
    """A single economic calendar event."""
    timestamp: datetime
    title: str
    impact: str       # "high", "medium", "low"
    currency: str = ""
    actual: str = ""
    forecast: str = ""
    previous: str = ""


# ── News Filter ──────────────────────────────────────────────────────────

class NewsFilter:
    """
    Gate that answers: *is the given timestamp inside a news blackout?*

    Usage
    -----
    >>> nf = NewsFilter(cfg)
    >>> nf.load_csv("data/economic_calendar.csv")
    >>> nf.is_blackout(some_timestamp)
    True
    """

    def __init__(self, cfg: NewsConfig) -> None:
        self._cfg = cfg
        self._events: list[NewsEvent] = []
        self._before = timedelta(minutes=cfg.blackout_minutes_before)
        self._after = timedelta(minutes=cfg.blackout_minutes_after)
        self._impact_set = set(cfg.impact_levels)

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    # ── Loading ──────────────────────────────────────────────────────

    def load_csv(self, path: str | Path) -> None:
        """
        Load a CSV calendar.  Expected columns:
        ``datetime, title, impact[, currency, actual, forecast, previous]``
        """
        path = Path(path)
        if not path.exists():
            log.warning("News calendar not found at %s — filter disabled", path)
            return

        with open(path, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    ts = datetime.fromisoformat(row["datetime"])
                    evt = NewsEvent(
                        timestamp=ts,
                        title=row.get("title", ""),
                        impact=row.get("impact", "low").lower(),
                        currency=row.get("currency", ""),
                        actual=row.get("actual", ""),
                        forecast=row.get("forecast", ""),
                        previous=row.get("previous", ""),
                    )
                    self._events.append(evt)
                except (KeyError, ValueError) as exc:
                    log.debug("Skipping calendar row: %s", exc)

        self._events.sort(key=lambda e: e.timestamp)
        log.info("Loaded %d news events", len(self._events))

    def add_events(self, events: Sequence[NewsEvent]) -> None:
        """Programmatically add events (e.g. from an API)."""
        self._events.extend(events)
        self._events.sort(key=lambda e: e.timestamp)

    # ── Query ────────────────────────────────────────────────────────

    def is_blackout(self, ts: datetime) -> bool:
        """
        Return True if *ts* is within the blackout window of any
        high-impact event.
        """
        if not self._cfg.enabled or not self._events:
            return False

        for evt in self._events:
            if evt.impact not in self._impact_set:
                continue
            window_start = evt.timestamp - self._before
            window_end = evt.timestamp + self._after
            if window_start <= ts <= window_end:
                return True

            # Early exit: events are sorted — if we're past the window
            if evt.timestamp - self._before > ts:
                break

        return False

    def get_upcoming(self, ts: datetime, horizon_minutes: int = 60) -> list[NewsEvent]:
        """Return high-impact events within *horizon_minutes* of *ts*."""
        cutoff = ts + timedelta(minutes=horizon_minutes)
        return [
            e
            for e in self._events
            if e.impact in self._impact_set
            and ts <= e.timestamp <= cutoff
        ]
