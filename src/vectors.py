"""
vectors.py — Multi-timeframe vector detection engine.

Uses a **tick-proxy composite score** to approximate tick-frequency
clustering when raw tick data is unavailable (which it is for most
equity bar feeds).

Responsibilities:
  - Compute per-bar tick-proxy score
  - Classify candles as primary / secondary / non-vector
  - Track external vectors with freshness (bar age)
  - Update recovery state of all tracked vectors every bar
  - Detect multi-timeframe confluence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.config import VectorConfig
from src.indicators import ZScoreTracker
from src.models import (
    Candle,
    Direction,
    VectorCandle,
    VectorSource,
    VectorStrength,
)


# ── Tick-Proxy Scoring ───────────────────────────────────────────────────

def compute_tick_proxy_score(
    candle: Candle,
    volume_z: float,
    range_z: float,
) -> float:
    """
    Approximate tick-frequency intensity from observable bar data.

    Components (weighted):
      - Volume z-score  (40 %): unusual volume ≈ clustered ticks
      - Range z-score   (40 %): large range ≈ rapid directional movement
      - Body fraction   (20 %): directional conviction multiplier

    Returns a dimensionless score.  Primary vector threshold = 2.0,
    secondary = 1.5 by default.
    """
    body_frac = candle.body_fraction
    return (volume_z * 0.4) + (range_z * 0.4) + (body_frac * 5.0 * 0.2)


# ── Per-Timeframe Vector Tracker ─────────────────────────────────────────

class TimeframeVectorTracker:
    """
    Tracks vectors for a single timeframe (e.g. "5m").

    External vectors are kept in a list and pruned when they exceed
    ``max_age_bars`` or become fully recovered.
    """

    def __init__(self, timeframe: str, cfg: VectorConfig) -> None:
        self.timeframe = timeframe
        self._cfg = cfg

        # Rolling stats for z-score computation
        self._vol_z = ZScoreTracker(period=cfg.lookback)
        self._rng_z = ZScoreTracker(period=cfg.lookback)

        # Tracked external vectors (newest first)
        self.external_vectors: list[VectorCandle] = []

        self._bar_count: int = 0

    # ── Public API ───────────────────────────────────────────────────

    def process_bar(
        self,
        candle: Candle,
        is_brinks_session: bool,
    ) -> VectorCandle | None:
        """
        Feed a new bar.  Returns a ``VectorCandle`` if the bar qualifies,
        else ``None``.  Also updates recovery state of all tracked vectors.
        """
        self._bar_count += 1

        # Update rolling statistics
        vol_z = self._vol_z.update(candle.volume)
        rng_z = self._rng_z.update(candle.range)

        # Update recovery on ALL existing external vectors
        for vec in self.external_vectors:
            vec.update_recovery(candle.high, candle.low)

        # Prune stale / fully-recovered external vectors
        self._prune_external(candle.bar_index)

        # Check if this bar is a vector
        if not self._vol_z.ready:
            return None

        score = compute_tick_proxy_score(candle, vol_z, rng_z)

        if score < self._cfg.secondary_threshold:
            return None
        if candle.body_fraction < self._cfg.body_fraction_min:
            return None

        strength = (
            VectorStrength.PRIMARY
            if score >= self._cfg.primary_threshold
            else VectorStrength.SECONDARY
        )
        direction = Direction.BULL if candle.is_bullish else Direction.BEAR

        vec = VectorCandle(
            direction=direction,
            high=candle.high,
            low=candle.low,
            body_high=candle.body_high,
            body_low=candle.body_low,
            bar_index=candle.bar_index,
            timestamp=candle.timestamp,
            timeframe=self.timeframe,
            source=VectorSource.INTERNAL if is_brinks_session else VectorSource.EXTERNAL,
            strength=strength,
            tick_proxy_score=score,
        )

        if not is_brinks_session:
            self.external_vectors.insert(0, vec)  # newest first

        return vec

    def get_fresh_external(
        self,
        direction: Direction,
        current_bar: int,
    ) -> list[VectorCandle]:
        """Return external vectors of the given direction that are fresh and unrecovered."""
        return [
            v
            for v in self.external_vectors
            if v.direction == direction
            and not v.is_fully_recovered
            and (current_bar - v.bar_index) <= self._cfg.max_external_age_bars
        ]

    # ── Internal ─────────────────────────────────────────────────────

    def _prune_external(self, current_bar: int) -> None:
        self.external_vectors = [
            v
            for v in self.external_vectors
            if not v.is_fully_recovered
            and (current_bar - v.bar_index) <= self._cfg.max_external_age_bars * 2
        ]


# ── Multi-Timeframe Vector Engine ────────────────────────────────────────

class VectorEngine:
    """
    Orchestrates vector detection across multiple timeframes.

    The primary timeframe (e.g. "5m") drives the box-builder and signal
    engine.  Lower/higher timeframes contribute confluence information.
    """

    def __init__(self, cfg: VectorConfig) -> None:
        self._cfg = cfg
        self.trackers: dict[str, TimeframeVectorTracker] = {
            tf: TimeframeVectorTracker(tf, cfg) for tf in cfg.timeframes
        }
        self.primary_tf = cfg.primary_timeframe

    @property
    def primary_tracker(self) -> TimeframeVectorTracker:
        return self.trackers[self.primary_tf]

    def process_bar(
        self,
        candle: Candle,
        is_brinks_session: bool,
    ) -> VectorCandle | None:
        """
        Process a bar on its matching timeframe tracker.
        Returns the detected vector (if any) on that timeframe.
        """
        tf = candle.timeframe
        tracker = self.trackers.get(tf)
        if tracker is None:
            return None

        vec = tracker.process_bar(candle, is_brinks_session)

        # Check for multi-timeframe confluence
        if vec is not None:
            self._check_confluence(vec)

        return vec

    def update_recovery_all(self, candle_high: float, candle_low: float) -> None:
        """Update recovery state on ALL vectors across ALL timeframes."""
        for tracker in self.trackers.values():
            for v in tracker.external_vectors:
                v.update_recovery(candle_high, candle_low)

    def get_fresh_external(
        self,
        direction: Direction,
        current_bar: int,
        timeframe: str | None = None,
    ) -> list[VectorCandle]:
        """
        Return fresh, unrecovered external vectors of the given direction.
        If timeframe is None, searches the primary tracker.
        """
        tf = timeframe or self.primary_tf
        tracker = self.trackers.get(tf)
        if tracker is None:
            return []
        return tracker.get_fresh_external(direction, current_bar)

    def get_all_fresh_external(
        self,
        direction: Direction,
        current_bar: int,
    ) -> list[VectorCandle]:
        """Return fresh external vectors across ALL timeframes, sorted by distance."""
        result: list[VectorCandle] = []
        for tracker in self.trackers.values():
            result.extend(tracker.get_fresh_external(direction, current_bar))
        return result

    # ── Confluence ───────────────────────────────────────────────────

    def _check_confluence(self, vec: VectorCandle) -> None:
        """
        If another timeframe has a vector overlapping the same price zone,
        mark both as confluent.
        """
        for tf, tracker in self.trackers.items():
            if tf == vec.timeframe:
                continue
            for other in tracker.external_vectors[-10:]:  # check recent only
                if other.is_fully_recovered:
                    continue
                if _zones_overlap(vec, other):
                    if tf not in vec.confluent_timeframes:
                        vec.confluent_timeframes.append(tf)
                    if vec.timeframe not in other.confluent_timeframes:
                        other.confluent_timeframes.append(vec.timeframe)


def _zones_overlap(a: VectorCandle, b: VectorCandle) -> bool:
    """Return True if two vectors' high-low ranges overlap."""
    return a.low <= b.high and b.low <= a.high
