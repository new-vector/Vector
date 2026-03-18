"""
signals.py — Entry signal engine.

Implements the three Hybrid System entry types:
  1. Reversal to internal vector
  2. Continuation breakout
  3. Momentum entry

Each signal is gated by the full filter stack: EMA trend, mid-hold,
trade window, weekday, daily limit, news blackout, and position state.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.brinks_box import BrinksBoxBuilder
from src.config import TradeLogicConfig
from src.indicators import EMA
from src.models import (
    BrinksBox,
    Candle,
    Direction,
    Signal,
    SignalType,
    VectorCandle,
)
from src.news import NewsFilter
from src.session import SessionManager
from src.vectors import VectorEngine

log = logging.getLogger(__name__)


class SignalEngine:
    """
    Evaluates all entry conditions on each primary-timeframe bar and
    emits a ``Signal`` (or ``None``) for downstream order handling.
    """

    def __init__(
        self,
        cfg: TradeLogicConfig,
        session_mgr: SessionManager,
        box_builder: BrinksBoxBuilder,
        vector_engine: VectorEngine,
        news_filter: NewsFilter,
        ema_fast: EMA,
        ema_slow: EMA,
    ) -> None:
        self._cfg = cfg
        self._sm = session_mgr
        self._bb = box_builder
        self._ve = vector_engine
        self._nf = news_filter
        self._ema_fast = ema_fast
        self._ema_slow = ema_slow

    # ── Main entry point ─────────────────────────────────────────────

    def evaluate(
        self,
        candle: Candle,
        position_flat: bool,
        trades_today: int,
        max_trades_per_day: int,
    ) -> Signal | None:
        """
        Evaluate all entry conditions against the current bar.

        Returns
        -------
        Signal  if an entry condition fires
        None    otherwise
        """
        # ── Gate checks (fastest rejections first) ───────────────────
        if not position_flat:
            return None

        if not self._sm.can_trade(candle.timestamp):
            return None

        box = self._bb.box
        if not box.is_ready:
            return None

        if not self._sm.trade_window.is_active(candle.timestamp):
            return None

        if max_trades_per_day > 0 and trades_today >= max_trades_per_day:
            return None

        if self._nf.is_blackout(candle.timestamp):
            log.debug("News blackout at %s — skipping signal", candle.timestamp)
            return None

        # ── Trend filters ────────────────────────────────────────────
        long_trend_ok = (
            not self._cfg.use_ema_filter
            or self._ema_fast.value > self._ema_slow.value
        )
        short_trend_ok = (
            not self._cfg.use_ema_filter
            or self._ema_fast.value < self._ema_slow.value
        )

        # ── Mid-hold filter ──────────────────────────────────────────
        mid_long_ok = (
            not self._cfg.require_mid_hold
            or candle.close >= box.mid
        )
        mid_short_ok = (
            not self._cfg.require_mid_hold
            or candle.close <= box.mid
        )

        # ── Type 1: Reversal to internal vector ─────────────────────
        if self._cfg.allow_reversal:
            sig = self._check_reversal(candle, box, long_trend_ok, short_trend_ok, mid_long_ok, mid_short_ok)
            if sig is not None:
                return sig

        # ── Type 2: Continuation breakout ────────────────────────────
        if self._cfg.allow_continuation:
            sig = self._check_continuation(candle, box, long_trend_ok, short_trend_ok, mid_long_ok, mid_short_ok)
            if sig is not None:
                return sig

        # ── Type 3: Momentum entry ───────────────────────────────────
        if self._cfg.allow_momentum_entry:
            sig = self._check_momentum(candle, box, long_trend_ok, short_trend_ok, mid_long_ok, mid_short_ok)
            if sig is not None:
                return sig

        return None

    # ── Entry type implementations ───────────────────────────────────

    def _check_reversal(
        self,
        candle: Candle,
        box: BrinksBox,
        long_ok: bool,
        short_ok: bool,
        mid_long: bool,
        mid_short: bool,
    ) -> Signal | None:
        """
        Reversal-to-vector:
        - Internal bear vector unrecovered → price closes above its high → LONG
        - Internal bull vector unrecovered → price closes below its low → SHORT
        """
        # ── Long reversal ────────────────────────────────────────────
        if long_ok and mid_long:
            for vec in box.unrecovered_internal_bear_vectors:
                if candle.close > vec.high:
                    target_vec = self._find_target_vector(Direction.BULL, candle)
                    return Signal(
                        signal_type=SignalType.REVERSAL_LONG,
                        timestamp=candle.timestamp,
                        bar_index=candle.bar_index,
                        price=candle.close,
                        reason=f"Reversal long: close {candle.close:.2f} > bear vec high {vec.high:.2f}",
                        triggering_vector=vec,
                        target_vector=target_vec,
                    )

        # ── Short reversal ───────────────────────────────────────────
        if short_ok and mid_short:
            for vec in box.unrecovered_internal_bull_vectors:
                if candle.close < vec.low:
                    target_vec = self._find_target_vector(Direction.BEAR, candle)
                    return Signal(
                        signal_type=SignalType.REVERSAL_SHORT,
                        timestamp=candle.timestamp,
                        bar_index=candle.bar_index,
                        price=candle.close,
                        reason=f"Reversal short: close {candle.close:.2f} < bull vec low {vec.low:.2f}",
                        triggering_vector=vec,
                        target_vector=target_vec,
                    )

        return None

    def _check_continuation(
        self,
        candle: Candle,
        box: BrinksBox,
        long_ok: bool,
        short_ok: bool,
        mid_long: bool,
        mid_short: bool,
    ) -> Signal | None:
        """Continuation breakout of Brinks high/low via decisive close."""
        if long_ok and mid_long and candle.close > box.session_high:
            target_vec = self._find_target_vector(Direction.BULL, candle)
            return Signal(
                signal_type=SignalType.CONTINUATION_LONG,
                timestamp=candle.timestamp,
                bar_index=candle.bar_index,
                price=candle.close,
                reason=f"Continuation long: close {candle.close:.2f} > box high {box.session_high:.2f}",
                target_vector=target_vec,
            )

        if short_ok and mid_short and candle.close < box.session_low:
            target_vec = self._find_target_vector(Direction.BEAR, candle)
            return Signal(
                signal_type=SignalType.CONTINUATION_SHORT,
                timestamp=candle.timestamp,
                bar_index=candle.bar_index,
                price=candle.close,
                reason=f"Continuation short: close {candle.close:.2f} < box low {box.session_low:.2f}",
                target_vector=target_vec,
            )

        return None

    def _check_momentum(
        self,
        candle: Candle,
        box: BrinksBox,
        long_ok: bool,
        short_ok: bool,
        mid_long: bool,
        mid_short: bool,
    ) -> Signal | None:
        """
        Momentum entry: reversal setup exists but price does not
        retrace — enter at Brinks high/low as a momentum play.
        """
        # Only fire if there are unrecovered vectors that *haven't*
        # triggered a standard reversal (i.e. close hasn't crossed yet
        # but price is pushing toward box edge)
        if long_ok and mid_long:
            if box.unrecovered_internal_bear_vectors and candle.close >= box.session_high:
                target_vec = self._find_target_vector(Direction.BULL, candle)
                return Signal(
                    signal_type=SignalType.MOMENTUM_LONG,
                    timestamp=candle.timestamp,
                    bar_index=candle.bar_index,
                    price=candle.close,
                    reason="Momentum long: unrecovered bear vecs + break of box high",
                    target_vector=target_vec,
                )

        if short_ok and mid_short:
            if box.unrecovered_internal_bull_vectors and candle.close <= box.session_low:
                target_vec = self._find_target_vector(Direction.BEAR, candle)
                return Signal(
                    signal_type=SignalType.MOMENTUM_SHORT,
                    timestamp=candle.timestamp,
                    bar_index=candle.bar_index,
                    price=candle.close,
                    reason="Momentum short: unrecovered bull vecs + break of box low",
                    target_vector=target_vec,
                )

        return None

    # ── Target vector selection ──────────────────────────────────────

    def _find_target_vector(
        self,
        trade_direction: Direction,
        candle: Candle,
    ) -> VectorCandle | None:
        """
        Find the nearest unrecovered external vector in the trade
        direction.  For longs → find bear vectors above price.
        For shorts → find bull vectors below price.
        """
        if trade_direction == Direction.BULL:
            # Looking for bear vectors ABOVE current price
            candidates = self._ve.get_all_fresh_external(Direction.BEAR, candle.bar_index)
            above = [v for v in candidates if v.body_low > candle.close]
            if above:
                return min(above, key=lambda v: v.body_low)
        else:
            # Looking for bull vectors BELOW current price
            candidates = self._ve.get_all_fresh_external(Direction.BULL, candle.bar_index)
            below = [v for v in candidates if v.body_high < candle.close]
            if below:
                return max(below, key=lambda v: v.body_high)

        return None
