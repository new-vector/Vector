"""
risk.py — Stop-loss, target, and position-sizing calculations.

Supports four stop modes (opposite box side, box mid, ATR, invalidation)
and dynamic target selection using external vector zones or fallback R:R.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.config import RiskConfig
from src.indicators import ATR
from src.models import (
    BrinksBox,
    Candle,
    Direction,
    OrderSide,
    Signal,
    SignalType,
    StopMode,
    VectorCandle,
)


@dataclass(slots=True)
class RiskParams:
    """Computed stop / target / size for a given signal."""
    stop_price: float
    target_price: float
    risk_per_share: float
    reward_per_share: float
    rr_ratio: float
    quantity: int


class RiskManager:
    """
    Computes stop-loss price, profit target, and position size for a
    given signal + box context.
    """

    def __init__(self, cfg: RiskConfig, atr: ATR, tick_size: float = 0.01) -> None:
        self._cfg = cfg
        self._atr = atr
        self._tick = tick_size

    def compute(
        self,
        signal: Signal,
        box: BrinksBox,
        entry_price: float,
        equity: float,
    ) -> RiskParams | None:
        """
        Return ``RiskParams`` for the signal, or ``None`` if the trade
        geometry is invalid (e.g. stop is on the wrong side of entry).
        """
        is_long = signal.signal_type in (
            SignalType.REVERSAL_LONG,
            SignalType.CONTINUATION_LONG,
            SignalType.MOMENTUM_LONG,
        )
        buffer = self._tick * self._cfg.buffer_ticks
        stop_mode = StopMode(self._cfg.stop_mode)

        # ── Stop price ───────────────────────────────────────────────
        stop_price = self._compute_stop(
            stop_mode, is_long, entry_price, box, signal, buffer,
        )

        # Validate stop is on the right side
        if is_long and stop_price >= entry_price:
            return None
        if not is_long and stop_price <= entry_price:
            return None

        # ── Target price ─────────────────────────────────────────────
        risk = abs(entry_price - stop_price)
        target_price = self._compute_target(
            is_long, entry_price, risk, signal.target_vector,
        )

        # ── Position size ────────────────────────────────────────────
        quantity = self._compute_size(equity, risk, entry_price)
        if quantity < 1:
            return None

        reward = abs(target_price - entry_price)
        rr = reward / risk if risk > 0 else 0.0

        return RiskParams(
            stop_price=round(stop_price, 4),
            target_price=round(target_price, 4),
            risk_per_share=round(risk, 4),
            reward_per_share=round(reward, 4),
            rr_ratio=round(rr, 2),
            quantity=quantity,
        )

    # ── Stop calculation ─────────────────────────────────────────────

    def _compute_stop(
        self,
        mode: StopMode,
        is_long: bool,
        entry: float,
        box: BrinksBox,
        signal: Signal,
        buffer: float,
    ) -> float:
        if mode == StopMode.OPPOSITE_BOX_SIDE:
            return (box.session_low - buffer) if is_long else (box.session_high + buffer)

        if mode == StopMode.BOX_MID:
            return (box.mid - buffer) if is_long else (box.mid + buffer)

        if mode == StopMode.ATR:
            atr_val = self._atr.value if not math.isnan(self._atr.value) else 0.0
            distance = atr_val * self._cfg.atr_multiplier
            return (entry - distance) if is_long else (entry + distance)

        if mode == StopMode.INVALIDATION:
            return self._invalidation_stop(is_long, entry, box, signal, buffer)

        # Fallback: opposite box side
        return (box.session_low - buffer) if is_long else (box.session_high + buffer)

    def _invalidation_stop(
        self,
        is_long: bool,
        entry: float,
        box: BrinksBox,
        signal: Signal,
        buffer: float,
    ) -> float:
        """
        Invalidation stop: for longs, stop at lowest internal bull
        vector low; for shorts, stop at highest internal bear vector high.
        Falls back to opposite box side.
        """
        if is_long:
            vecs = box.internal_bull_vectors
            if vecs:
                return min(v.low for v in vecs) - buffer
            return box.session_low - buffer
        else:
            vecs = box.internal_bear_vectors
            if vecs:
                return max(v.high for v in vecs) + buffer
            return box.session_high + buffer

    # ── Target calculation ───────────────────────────────────────────

    def _compute_target(
        self,
        is_long: bool,
        entry: float,
        risk: float,
        target_vector: VectorCandle | None,
    ) -> float:
        """
        Priority: external vector zone → fallback R:R.
        For longs, use the target vector's body_low (conservative).
        For shorts, use the target vector's body_high.
        """
        if target_vector is not None:
            if is_long and target_vector.body_low > entry:
                return target_vector.body_low
            if not is_long and target_vector.body_high < entry:
                return target_vector.body_high

        # Fallback: fixed R:R
        rr = self._cfg.rr_target
        return entry + risk * rr if is_long else entry - risk * rr

    # ── Position sizing ──────────────────────────────────────────────

    def _compute_size(self, equity: float, risk: float, entry: float) -> int:
        """
        Size based on max-equity-% risk.  Never risk more than 2 % of
        equity per trade (hard cap).
        """
        max_risk_dollars = equity * 0.02  # 2 % hard cap
        if risk <= 0:
            return 0
        shares = int(max_risk_dollars / risk)
        # Also cap by max_equity_pct of total equity
        max_shares_by_equity = int(equity * 0.10 / entry) if entry > 0 else 0
        return min(shares, max_shares_by_equity, 10_000)  # hard cap at 10k shares
