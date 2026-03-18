"""
engine.py — Main strategy orchestrator.

Processes bars in chronological order and wires together every component:
  SessionManager → BrinksBoxBuilder → VectorEngine → SignalEngine →
  RiskManager → PortfolioManager

Designed to be called identically by the backtester and the live runner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from src.brinks_box import BrinksBoxBuilder
from src.config import SystemConfig
from src.indicators import ATR, EMA
from src.models import (
    Candle,
    Direction,
    Order,
    OrderSide,
    Signal,
    SignalType,
    TradeResult,
    VectorCandle,
)
from src.news import NewsFilter
from src.portfolio import PortfolioManager
from src.risk import RiskManager
from src.session import SessionManager
from src.signals import SignalEngine
from src.vectors import VectorEngine

log = logging.getLogger(__name__)


# ── Engine Events (for dashboard / logging) ──────────────────────────────

@dataclass
class EngineEvent:
    """Lightweight event emitted by the engine each bar for observers."""
    timestamp: datetime
    bar_index: int
    brinks_active: bool = False
    trade_window_active: bool = False
    box_ready: bool = False
    box_high: float = 0.0
    box_low: float = 0.0
    box_mid: float = 0.0
    asian_high: float = 0.0
    asian_low: float = 0.0
    signal: Signal | None = None
    trade_result: TradeResult | None = None
    new_vector: VectorCandle | None = None
    equity: float = 0.0
    position_pnl: float = 0.0


class TradingEngine:
    """
    Stateful engine.  Feed bars with ``on_bar()`` in time order.

    Parameters
    ----------
    cfg : SystemConfig
        Full system configuration.
    """

    def __init__(self, cfg: SystemConfig) -> None:
        self.cfg = cfg

        # ── Sub-components ───────────────────────────────────────────
        self.session_mgr = SessionManager(cfg.session)
        self.box_builder = BrinksBoxBuilder(self.session_mgr)
        self.vector_engine = VectorEngine(cfg.vectors)

        self.ema_fast = EMA(cfg.trade_logic.ema_fast)
        self.ema_slow = EMA(cfg.trade_logic.ema_slow)
        self.atr = ATR(cfg.risk.atr_length)

        self.news_filter = NewsFilter(cfg.news)

        self.risk_mgr = RiskManager(cfg.risk, self.atr)

        max_trades = 1 if cfg.risk.one_trade_per_day else 0
        self.portfolio = PortfolioManager(
            initial_capital=cfg.backtest.initial_capital,
            commission_pct=cfg.backtest.commission_pct,
            max_trades_per_day=max_trades,
            flatten_after_window=cfg.risk.flatten_after_window,
            time_at_entry_max_bars=cfg.risk.time_at_entry_max_bars,
        )

        self.signal_engine = SignalEngine(
            cfg=cfg.trade_logic,
            session_mgr=self.session_mgr,
            box_builder=self.box_builder,
            vector_engine=self.vector_engine,
            news_filter=self.news_filter,
            ema_fast=self.ema_fast,
            ema_slow=self.ema_slow,
        )

        self._bar_count: int = 0
        self._events: list[EngineEvent] = []

    # ── Main bar handler ─────────────────────────────────────────────

    def on_bar(self, candle: Candle) -> EngineEvent:
        """
        Process a single bar.  This is the ONE call both the backtester
        and live runner make per bar.
        """
        self._bar_count += 1
        candle.bar_index = self._bar_count

        ts = candle.timestamp

        # ── 0. Day change ────────────────────────────────────────────
        is_new_day = self.session_mgr.is_new_day(ts)
        if is_new_day:
            day_id = self.session_mgr.day_id(ts)
            self.portfolio.on_new_day(day_id)

        # ── 1. Update sessions & Brinks Box ──────────────────────────
        self.box_builder.on_bar(candle)

        # ── 2. Detect vectors ────────────────────────────────────────
        is_brinks = self.box_builder.is_brinks_active
        new_vec = self.vector_engine.process_bar(candle, is_brinks)

        # Register internal vectors with the box
        if new_vec is not None and is_brinks:
            self.box_builder.add_internal_vector(new_vec)

        # ── 3. Update indicators ─────────────────────────────────────
        self.ema_fast.update(candle.close)
        self.ema_slow.update(candle.close)
        self.atr.update(candle.high, candle.low, candle.close)

        # ── 4. Check exits on existing position ──────────────────────
        trade_result = self.portfolio.check_exits(candle)

        # ── 5. Flatten after trade window? ───────────────────────────
        if trade_result is None and self.cfg.risk.flatten_after_window:
            tw_started, tw_ended = self.session_mgr.trade_window.check_transition(ts)
            if tw_ended and not self.portfolio.position.is_flat:
                trade_result = self.portfolio.flatten(candle)
        else:
            # Still need to check transition to keep state in sync
            self.session_mgr.trade_window.check_transition(ts)

        # ── 6. Generate entry signal ─────────────────────────────────
        signal: Signal | None = None
        if trade_result is None:  # Don't enter same bar we exit
            signal = self.signal_engine.evaluate(
                candle=candle,
                position_flat=self.portfolio.position.is_flat,
                trades_today=self.portfolio.trades_today,
                max_trades_per_day=self.portfolio.max_trades_per_day,
            )

        # ── 7. Size and submit order ─────────────────────────────────
        if signal is not None:
            equity = self.portfolio.cash
            risk_params = self.risk_mgr.compute(
                signal=signal,
                box=self.box_builder.box,
                entry_price=candle.close,
                equity=equity,
            )
            if risk_params is not None:
                side = (
                    OrderSide.BUY
                    if signal.signal_type in (
                        SignalType.REVERSAL_LONG,
                        SignalType.CONTINUATION_LONG,
                        SignalType.MOMENTUM_LONG,
                    )
                    else OrderSide.SELL
                )
                order = Order(
                    side=side,
                    entry_price=candle.close,
                    stop_price=risk_params.stop_price,
                    target_price=risk_params.target_price,
                    quantity=risk_params.quantity,
                    signal=signal,
                    fill_timestamp=candle.timestamp,
                    comment=signal.reason,
                )
                self.portfolio.open_position(order)
            else:
                log.debug("Risk check rejected signal: %s", signal.reason)
                signal = None  # Clear for the event

        # ── 8. Build event snapshot ──────────────────────────────────
        snap = self.portfolio.snapshot(candle)
        box = self.box_builder.box

        event = EngineEvent(
            timestamp=ts,
            bar_index=self._bar_count,
            brinks_active=self.box_builder.is_brinks_active,
            trade_window_active=self.session_mgr.trade_window.is_active(ts),
            box_ready=box.is_ready,
            box_high=box.session_high,
            box_low=box.session_low,
            box_mid=box.mid,
            asian_high=self.box_builder.asian_range.high,
            asian_low=self.box_builder.asian_range.low,
            signal=signal,
            trade_result=trade_result,
            new_vector=new_vec,
            equity=snap.equity,
            position_pnl=snap.unrealised_pnl,
        )
        self._events.append(event)
        return event

    # ── Accessors ────────────────────────────────────────────────────

    @property
    def events(self) -> list[EngineEvent]:
        return self._events

    @property
    def trade_journal(self) -> list[TradeResult]:
        return self.portfolio.trade_journal

    @property
    def total_bars(self) -> int:
        return self._bar_count
