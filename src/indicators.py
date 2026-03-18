"""
indicators.py — Incremental EMA, ATR, SMA, and z-score calculators.

All indicators are designed for streaming use: call ``update()`` with
each new bar and read ``.value`` for the current result.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field


# ── Exponential Moving Average ───────────────────────────────────────────

class EMA:
    """Incremental EMA matching Pine Script ``ta.ema``."""

    __slots__ = ("period", "multiplier", "value", "_count")

    def __init__(self, period: int) -> None:
        self.period = period
        self.multiplier = 2.0 / (period + 1)
        self.value: float = math.nan
        self._count: int = 0

    def update(self, price: float) -> float:
        self._count += 1
        if self._count == 1:
            self.value = price
        else:
            self.value = (price - self.value) * self.multiplier + self.value
        return self.value

    @property
    def ready(self) -> bool:
        return self._count >= self.period


# ── Simple Moving Average ────────────────────────────────────────────────

class SMA:
    """Rolling SMA backed by a deque.  O(1) update."""

    __slots__ = ("period", "value", "_buf", "_sum", "_count")

    def __init__(self, period: int) -> None:
        self.period = period
        self.value: float = math.nan
        self._buf: deque[float] = deque(maxlen=period)
        self._sum: float = 0.0
        self._count: int = 0

    def update(self, value: float) -> float:
        if len(self._buf) == self.period:
            self._sum -= self._buf[0]
        self._buf.append(value)
        self._sum += value
        self._count += 1
        self.value = self._sum / len(self._buf)
        return self.value

    @property
    def ready(self) -> bool:
        return len(self._buf) == self.period


# ── Rolling Standard Deviation ───────────────────────────────────────────

class RollingStd:
    """
    Welford-style rolling standard deviation over the last *period* values.
    Uses a deque so it is O(N) on recomputation but simple and correct.
    """

    __slots__ = ("period", "value", "mean", "_buf")

    def __init__(self, period: int) -> None:
        self.period = period
        self.value: float = math.nan
        self.mean: float = math.nan
        self._buf: deque[float] = deque(maxlen=period)

    def update(self, x: float) -> float:
        self._buf.append(x)
        n = len(self._buf)
        self.mean = sum(self._buf) / n
        if n < 2:
            self.value = 0.0
        else:
            self.value = math.sqrt(sum((v - self.mean) ** 2 for v in self._buf) / (n - 1))
        return self.value

    @property
    def ready(self) -> bool:
        return len(self._buf) == self.period


# ── Average True Range ───────────────────────────────────────────────────

class ATR:
    """
    Wilder-smoothed ATR matching Pine Script ``ta.atr``.

    Requires ``update(high, low, close)``; the first call sets the
    previous-close seed.
    """

    __slots__ = ("period", "value", "_prev_close", "_count", "_alpha")

    def __init__(self, period: int) -> None:
        self.period = period
        self.value: float = math.nan
        self._prev_close: float = math.nan
        self._count: int = 0
        self._alpha: float = 1.0 / period

    def update(self, high: float, low: float, close: float) -> float:
        if math.isnan(self._prev_close):
            self._prev_close = close
            self.value = high - low
            return self.value

        true_range = max(
            high - low,
            abs(high - self._prev_close),
            abs(low - self._prev_close),
        )
        self._prev_close = close
        self._count += 1

        if self._count == 1:
            self.value = true_range
        elif self._count <= self.period:
            # Accumulate simple average for the seed period
            self.value = self.value + (true_range - self.value) / self._count
        else:
            # Wilder smoothing
            self.value = self.value + self._alpha * (true_range - self.value)

        return self.value

    @property
    def ready(self) -> bool:
        return self._count >= self.period


# ── Volume / Range Z-Score Tracker ───────────────────────────────────────

@dataclass
class ZScoreTracker:
    """
    Tracks a rolling mean + stddev and exposes a live z-score.
    Designed for volume and range z-score computation used by the
    tick-proxy vector scoring function.
    """
    period: int = 20
    _sma: SMA = field(init=False, repr=False)
    _std: RollingStd = field(init=False, repr=False)
    value: float = 0.0

    def __post_init__(self) -> None:
        self._sma = SMA(self.period)
        self._std = RollingStd(self.period)

    def update(self, x: float) -> float:
        self._sma.update(x)
        self._std.update(x)
        if self._std.ready and self._std.value > 1e-9:
            self.value = (x - self._sma.value) / self._std.value
        else:
            self.value = 0.0
        return self.value

    @property
    def mean(self) -> float:
        return self._sma.value

    @property
    def std(self) -> float:
        return self._std.value

    @property
    def ready(self) -> bool:
        return self._sma.ready and self._std.ready
