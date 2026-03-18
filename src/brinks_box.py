"""
brinks_box.py — Brinks Box session builder.

Accumulates the high/low of the 09:00-10:00 ET session, tracks internal
vectors, and integrates Asian session range context.
"""

from __future__ import annotations

from src.models import (
    AsianSessionRange,
    BrinksBox,
    Candle,
    VectorCandle,
)
from src.session import SessionManager


class BrinksBoxBuilder:
    """
    Stateful builder that is called once per primary-timeframe bar.

    Lifecycle per day:
      1. Asian session → accumulate ``asian_range``
      2. ``asian.finalise()`` → feed high/low into box
      3. Brinks session start → ``box.reset()``
      4. Brinks session bars → ``box.update(candle)``
      5. Brinks session end → ``box.finalise()``
      6. Trade window → box is ready, check for Asian sweeps
    """

    def __init__(self, session_mgr: SessionManager) -> None:
        self._sm = session_mgr
        self.box = BrinksBox()
        self.asian_range = AsianSessionRange()

        self._brinks_active = False
        self._asian_active = False

    # ── Per-bar interface ────────────────────────────────────────────

    def on_bar(self, candle: Candle) -> None:
        """Call once per primary-TF bar.  Manages all state transitions."""
        ts = candle.timestamp

        # ── Asian session ────────────────────────────────────────────
        asian_started, asian_ended = self._sm.asian.check_transition(ts)

        if asian_started:
            day_id = self._sm.day_id(ts)
            self.asian_range.reset(day_id)
            self._asian_active = True

        if self._asian_active and self._sm.asian.is_active(ts):
            self.asian_range.update(candle)

        if asian_ended:
            self.asian_range.finalise()
            self._asian_active = False

        # ── Brinks session ───────────────────────────────────────────
        brinks_started, brinks_ended = self._sm.brinks.check_transition(ts)

        if brinks_started:
            day_id = self._sm.day_id(ts)
            self.box.reset(day_id)
            # Feed Asian range into the new box
            if self.asian_range.is_complete:
                self.box.asian_session_high = self.asian_range.high
                self.box.asian_session_low = self.asian_range.low
            self._brinks_active = True

        if self._brinks_active and self._sm.brinks.is_active(ts):
            self.box.update(candle)
            # Check Asian sweep during Brinks formation
            self.box.check_asian_sweep(candle)

        if brinks_ended:
            self.box.finalise()
            self._brinks_active = False

        # Post-brinks: continue checking Asian sweeps and updating
        # internal vector recovery
        if self.box.is_ready:
            self.box.check_asian_sweep(candle)
            for v in self.box.internal_bull_vectors:
                v.update_recovery(candle.high, candle.low)
            for v in self.box.internal_bear_vectors:
                v.update_recovery(candle.high, candle.low)

    def add_internal_vector(self, vec: VectorCandle) -> None:
        """Register a vector formed during the Brinks session."""
        self.box.add_internal_vector(vec)

    @property
    def is_brinks_active(self) -> bool:
        return self._brinks_active

    @property
    def is_box_ready(self) -> bool:
        return self.box.is_ready
