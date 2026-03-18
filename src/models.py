"""
models.py — Core data structures for the Brinks Box Hybrid System.

Every component in the system consumes or produces these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Literal


# ── Enums ────────────────────────────────────────────────────────────────

class Direction(Enum):
    BULL = auto()
    BEAR = auto()


class VectorStrength(Enum):
    PRIMARY = auto()    # ≥200 % tick-proxy score
    SECONDARY = auto()  # ≥150 % tick-proxy score


class VectorSource(Enum):
    INTERNAL = auto()   # Formed during Brinks session
    EXTERNAL = auto()   # Formed outside Brinks session


class SignalType(Enum):
    REVERSAL_LONG = auto()
    REVERSAL_SHORT = auto()
    CONTINUATION_LONG = auto()
    CONTINUATION_SHORT = auto()
    MOMENTUM_LONG = auto()
    MOMENTUM_SHORT = auto()


class StopMode(Enum):
    OPPOSITE_BOX_SIDE = "opposite_box_side"
    BOX_MID = "box_mid"
    ATR = "atr"
    INVALIDATION = "invalidation"


class OrderSide(Enum):
    BUY = auto()
    SELL = auto()


class OrderStatus(Enum):
    PENDING = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()


class PositionStatus(Enum):
    FLAT = auto()
    LONG = auto()
    SHORT = auto()


# ── Candle ───────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Candle:
    """Single OHLCV bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_index: int = 0
    timeframe: str = "5m"

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def body_fraction(self) -> float:
        return self.body_size / self.range if self.range > 0 else 0.0

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


# ── Vector Candle ────────────────────────────────────────────────────────

@dataclass
class VectorCandle:
    """
    A candle with abnormal tick-frequency activity.  Tracks its own
    recovery state bar-by-bar so the strategy can distinguish between
    partially and fully recovered liquidity zones.
    """
    direction: Direction
    high: float
    low: float
    body_high: float
    body_low: float
    bar_index: int
    timestamp: datetime
    timeframe: str = "5m"
    source: VectorSource = VectorSource.EXTERNAL
    strength: VectorStrength = VectorStrength.PRIMARY
    tick_proxy_score: float = 0.0

    # Recovery tracking — updated each bar after formation
    recovery_high_reached: float = 0.0
    recovery_low_reached: float = 0.0
    is_fully_recovered: bool = False
    is_partially_recovered: bool = False

    # Multi-timeframe confluence
    confluent_timeframes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Initialise recovery extremes to the vector's own bounds
        if self.recovery_high_reached == 0.0:
            self.recovery_high_reached = self.low  # nothing penetrated yet
        if self.recovery_low_reached == 0.0:
            self.recovery_low_reached = self.high

    # ── Recovery logic ───────────────────────────────────────────────

    def update_recovery(self, candle_high: float, candle_low: float) -> None:
        """
        Call once per subsequent bar to track how far price has
        penetrated into this vector's range.
        """
        if self.is_fully_recovered:
            return

        # Track the maximum extent of price penetration
        self.recovery_high_reached = max(self.recovery_high_reached, candle_high)
        self.recovery_low_reached = min(self.recovery_low_reached, candle_low)

        if self.direction == Direction.BEAR:
            # Bear vector is recovered when price trades UP through the
            # full range — from its low back up through its high
            if self.recovery_high_reached >= self.high:
                self.is_fully_recovered = True
                self.is_partially_recovered = False
            elif self.recovery_high_reached > self.low:
                self.is_partially_recovered = True
        else:
            # Bull vector is recovered when price trades DOWN through
            # the full range — from its high back down through its low
            if self.recovery_low_reached <= self.low:
                self.is_fully_recovered = True
                self.is_partially_recovered = False
            elif self.recovery_low_reached < self.high:
                self.is_partially_recovered = True

    @property
    def recovery_pct(self) -> float:
        """Fraction of the vector range that has been recovered (0-1)."""
        rng = self.high - self.low
        if rng <= 0:
            return 0.0
        if self.direction == Direction.BEAR:
            penetration = self.recovery_high_reached - self.low
        else:
            penetration = self.high - self.recovery_low_reached
        return min(max(penetration / rng, 0.0), 1.0)


# ── Brinks Box ───────────────────────────────────────────────────────────

@dataclass
class BrinksBox:
    """The accumulated high/low/mid of the 09:00-10:00 ET session."""
    session_high: float = 0.0
    session_low: float = float("inf")
    mid: float = 0.0
    day_id: int = 0

    # ALL internal vectors (not just the most recent)
    internal_bull_vectors: list[VectorCandle] = field(default_factory=list)
    internal_bear_vectors: list[VectorCandle] = field(default_factory=list)

    is_ready: bool = False

    # Asian session context
    asian_session_high: float | None = None
    asian_session_low: float | None = None
    asian_range_swept_high: bool = False
    asian_range_swept_low: bool = False

    def reset(self, day_id: int) -> None:
        self.session_high = 0.0
        self.session_low = float("inf")
        self.mid = 0.0
        self.day_id = day_id
        self.internal_bull_vectors.clear()
        self.internal_bear_vectors.clear()
        self.is_ready = False
        self.asian_range_swept_high = False
        self.asian_range_swept_low = False

    def update(self, candle: Candle) -> None:
        self.session_high = max(self.session_high, candle.high)
        self.session_low = min(self.session_low, candle.low)

    def finalise(self) -> None:
        self.mid = (self.session_high + self.session_low) / 2.0
        self.is_ready = True

    def add_internal_vector(self, vec: VectorCandle) -> None:
        vec.source = VectorSource.INTERNAL
        if vec.direction == Direction.BULL:
            self.internal_bull_vectors.append(vec)
        else:
            self.internal_bear_vectors.append(vec)

    def check_asian_sweep(self, candle: Candle) -> None:
        if self.asian_session_high is not None and candle.high >= self.asian_session_high:
            self.asian_range_swept_high = True
        if self.asian_session_low is not None and candle.low <= self.asian_session_low:
            self.asian_range_swept_low = True

    @property
    def unrecovered_internal_bear_vectors(self) -> list[VectorCandle]:
        return [v for v in self.internal_bear_vectors if not v.is_fully_recovered]

    @property
    def unrecovered_internal_bull_vectors(self) -> list[VectorCandle]:
        return [v for v in self.internal_bull_vectors if not v.is_fully_recovered]


# ── Asian Session Range ──────────────────────────────────────────────────

@dataclass
class AsianSessionRange:
    """Tracks the Asian session (00:00-08:00 ET) high/low."""
    high: float = 0.0
    low: float = float("inf")
    is_complete: bool = False
    day_id: int = 0

    def reset(self, day_id: int) -> None:
        self.high = 0.0
        self.low = float("inf")
        self.is_complete = False
        self.day_id = day_id

    def update(self, candle: Candle) -> None:
        self.high = max(self.high, candle.high)
        self.low = min(self.low, candle.low)

    def finalise(self) -> None:
        self.is_complete = True


# ── Signals ──────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Signal:
    """An entry signal emitted by the signal engine."""
    signal_type: SignalType
    timestamp: datetime
    bar_index: int
    price: float                     # reference price at signal fire
    reason: str = ""                 # human-readable reason code
    triggering_vector: VectorCandle | None = None
    target_vector: VectorCandle | None = None


# ── Orders & Trades ──────────────────────────────────────────────────────

@dataclass
class Order:
    """Represents an order to be submitted to the broker or backtester."""
    side: OrderSide
    entry_price: float
    stop_price: float
    target_price: float
    quantity: int | float = 1
    signal: Signal | None = None
    status: OrderStatus = OrderStatus.PENDING
    fill_price: float = 0.0
    fill_timestamp: datetime | None = None
    order_id: str = ""
    comment: str = ""


@dataclass
class TradeResult:
    """A closed trade with PnL attribution."""
    side: OrderSide
    entry_price: float
    exit_price: float
    quantity: int | float
    entry_time: datetime
    exit_time: datetime
    pnl: float = 0.0
    commission: float = 0.0
    net_pnl: float = 0.0
    signal_type: SignalType | None = None
    exit_reason: str = ""          # "target", "stop", "flatten", "time_exit"
    bars_held: int = 0


# ── Portfolio Snapshot ───────────────────────────────────────────────────

@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state for equity-curve tracking."""
    timestamp: datetime
    equity: float
    cash: float
    position_value: float
    unrealised_pnl: float
    realised_pnl: float
    position_status: PositionStatus = PositionStatus.FLAT
