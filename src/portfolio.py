"""
portfolio.py — Position tracking, daily trade limits, and trade journal.

Lightweight portfolio manager that tracks a single-instrument position
(matching the one-trade-per-day constraint of the Brinks system).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from src.models import (
    Candle,
    Order,
    OrderSide,
    OrderStatus,
    PortfolioSnapshot,
    PositionStatus,
    TradeResult,
)

log = logging.getLogger(__name__)


@dataclass
class Position:
    """Current open position."""
    side: OrderSide = OrderSide.BUY
    quantity: int = 0
    entry_price: float = 0.0
    entry_time: datetime | None = None
    entry_bar: int = 0
    stop_price: float = 0.0
    target_price: float = 0.0
    order: Order | None = None

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    @property
    def status(self) -> PositionStatus:
        if self.quantity == 0:
            return PositionStatus.FLAT
        return PositionStatus.LONG if self.side == OrderSide.BUY else PositionStatus.SHORT

    def unrealised_pnl(self, current_price: float) -> float:
        if self.is_flat:
            return 0.0
        if self.side == OrderSide.BUY:
            return (current_price - self.entry_price) * self.quantity
        return (self.entry_price - current_price) * self.quantity


class PortfolioManager:
    """
    Manages position lifecycle and maintains a trade journal.

    Call flow per bar:
      1. ``check_exits(candle)`` — checks stop/target/flatten
      2. ``open_position(order)`` — opens new position from signal
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        commission_pct: float = 0.04,
        max_trades_per_day: int = 1,
        flatten_after_window: bool = True,
        time_at_entry_max_bars: int = 10,
    ) -> None:
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_pct = commission_pct / 100.0  # Convert from percent
        self.max_trades_per_day = max_trades_per_day
        self.flatten_after_window = flatten_after_window
        self.time_at_entry_max_bars = time_at_entry_max_bars

        self.position = Position()
        self.trades_today: int = 0
        self.trade_journal: list[TradeResult] = []
        self.equity_curve: list[PortfolioSnapshot] = []

        self._current_day: int = -1

    # ── Daily reset ──────────────────────────────────────────────────

    def on_new_day(self, day_id: int) -> None:
        if day_id != self._current_day:
            self._current_day = day_id
            self.trades_today = 0

    # ── Position management ──────────────────────────────────────────

    def can_trade(self) -> bool:
        return (
            self.position.is_flat
            and (self.max_trades_per_day <= 0 or self.trades_today < self.max_trades_per_day)
        )

    def open_position(self, order: Order) -> None:
        """Fill an order and open a position."""
        commission = abs(order.entry_price * order.quantity * self.commission_pct)
        self.cash -= commission

        self.position = Position(
            side=order.side,
            quantity=order.quantity,
            entry_price=order.entry_price,
            entry_time=order.fill_timestamp,
            entry_bar=0,  # Set externally by engine
            stop_price=order.stop_price,
            target_price=order.target_price,
            order=order,
        )

        order.status = OrderStatus.FILLED
        order.fill_price = order.entry_price
        self.trades_today += 1

        log.info(
            "OPENED %s %d @ %.2f  stop=%.2f  target=%.2f",
            order.side.name,
            order.quantity,
            order.entry_price,
            order.stop_price,
            order.target_price,
        )

    def check_exits(self, candle: Candle) -> TradeResult | None:
        """
        Check whether the current position should be closed.

        Stop and target are evaluated against the bar's high/low
        (simulating intrabar fills for backtesting).
        """
        if self.position.is_flat:
            return None

        pos = self.position

        # ── Stop hit? ────────────────────────────────────────────────
        if pos.side == OrderSide.BUY and candle.low <= pos.stop_price:
            return self._close_position(pos.stop_price, candle, "stop")

        if pos.side == OrderSide.SELL and candle.high >= pos.stop_price:
            return self._close_position(pos.stop_price, candle, "stop")

        # ── Target hit? ──────────────────────────────────────────────
        if pos.side == OrderSide.BUY and candle.high >= pos.target_price:
            return self._close_position(pos.target_price, candle, "target")

        if pos.side == OrderSide.SELL and candle.low <= pos.target_price:
            return self._close_position(pos.target_price, candle, "target")

        # ── Time-at-entry exit ───────────────────────────────────────
        if self.time_at_entry_max_bars > 0:
            pos.entry_bar += 1
            if pos.entry_bar >= self.time_at_entry_max_bars:
                # Price hasn't moved in the intended direction
                if pos.side == OrderSide.BUY and candle.close <= pos.entry_price:
                    return self._close_position(candle.close, candle, "time_exit")
                if pos.side == OrderSide.SELL and candle.close >= pos.entry_price:
                    return self._close_position(candle.close, candle, "time_exit")

        return None

    def flatten(self, candle: Candle) -> TradeResult | None:
        """Force-close any open position (end of trade window)."""
        if self.position.is_flat:
            return None
        return self._close_position(candle.close, candle, "flatten")

    # ── Equity tracking ──────────────────────────────────────────────

    def snapshot(self, candle: Candle) -> PortfolioSnapshot:
        unrealised = self.position.unrealised_pnl(candle.close)
        realised = sum(t.net_pnl for t in self.trade_journal)
        equity = self.cash + unrealised
        if not self.position.is_flat:
            equity += self.position.entry_price * self.position.quantity  # gross position value
        snap = PortfolioSnapshot(
            timestamp=candle.timestamp,
            equity=equity,
            cash=self.cash,
            position_value=self.position.entry_price * self.position.quantity if not self.position.is_flat else 0.0,
            unrealised_pnl=unrealised,
            realised_pnl=realised,
            position_status=self.position.status,
        )
        self.equity_curve.append(snap)
        return snap

    # ── Internal ─────────────────────────────────────────────────────

    def _close_position(
        self,
        exit_price: float,
        candle: Candle,
        reason: str,
    ) -> TradeResult:
        pos = self.position
        commission = abs(exit_price * pos.quantity * self.commission_pct)
        self.cash -= commission

        if pos.side == OrderSide.BUY:
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        total_commission = commission + abs(pos.entry_price * pos.quantity * self.commission_pct)

        result = TradeResult(
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            entry_time=pos.entry_time or candle.timestamp,
            exit_time=candle.timestamp,
            pnl=pnl,
            commission=total_commission,
            net_pnl=pnl - total_commission,
            signal_type=pos.order.signal.signal_type if pos.order and pos.order.signal else None,
            exit_reason=reason,
            bars_held=pos.entry_bar,
        )
        self.trade_journal.append(result)
        self.cash += pnl  # add gross pnl to cash (commissions already deducted)

        log.info(
            "CLOSED %s %d @ %.2f  pnl=%.2f  reason=%s",
            pos.side.name,
            pos.quantity,
            exit_price,
            result.net_pnl,
            reason,
        )

        # Reset position
        self.position = Position()
        return result
