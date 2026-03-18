"""
alpaca_adapter.py — Alpaca Markets broker adapter.

Implements ``BrokerAdapter`` using ``alpaca-py`` for both paper and
live trading.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from src.live.broker import BrokerAdapter
from src.models import Order, OrderSide, OrderStatus

log = logging.getLogger(__name__)


class AlpacaAdapter(BrokerAdapter):
    """
    Alpaca REST + WebSocket adapter.

    Set environment variables:
      - APCA_API_KEY_ID
      - APCA_API_SECRET_KEY
      - APCA_API_BASE_URL (optional; defaults to paper)
    """

    def __init__(self, paper: bool = True) -> None:
        self._paper = paper
        self._trading_client = None
        self._key = os.environ.get("APCA_API_KEY_ID", "")
        self._secret = os.environ.get("APCA_API_SECRET_KEY", "")

    async def connect(self) -> None:
        from alpaca.trading.client import TradingClient

        self._trading_client = TradingClient(
            self._key,
            self._secret,
            paper=self._paper,
        )
        acct = self._trading_client.get_account()
        log.info(
            "Connected to Alpaca (%s)  equity=$%s",
            "PAPER" if self._paper else "LIVE",
            acct.equity,
        )

    async def disconnect(self) -> None:
        self._trading_client = None
        log.info("Disconnected from Alpaca")

    async def submit_order(self, order: Order) -> str:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide as AlpacaSide, TimeInForce

        if self._trading_client is None:
            raise RuntimeError("Not connected to Alpaca")

        side = AlpacaSide.BUY if order.side == OrderSide.BUY else AlpacaSide.SELL

        req = MarketOrderRequest(
            symbol=order.comment.split(":")[0] if ":" in order.comment else "SPY",
            qty=order.quantity,
            side=side,
            time_in_force=TimeInForce.DAY,
        )

        result = self._trading_client.submit_order(req)
        order.order_id = str(result.id)
        order.status = OrderStatus.PENDING

        log.info("Submitted order %s  %s %d", order.order_id, side.name, order.quantity)

        # TODO: Set up bracket order with stop and limit for stop_price / target_price
        # Alpaca supports bracket orders via OrderClass.BRACKET
        return order.order_id

    async def cancel_order(self, order_id: str) -> bool:
        if self._trading_client is None:
            return False
        try:
            self._trading_client.cancel_order_by_id(order_id)
            return True
        except Exception as exc:
            log.error("Cancel failed for %s: %s", order_id, exc)
            return False

    async def get_position(self, symbol: str) -> dict:
        if self._trading_client is None:
            return {}
        try:
            pos = self._trading_client.get_open_position(symbol)
            return {
                "qty": int(pos.qty),
                "avg_entry_price": float(pos.avg_entry_price),
                "market_value": float(pos.market_value),
                "unrealized_pnl": float(pos.unrealized_pl),
            }
        except Exception:
            return {"qty": 0, "avg_entry_price": 0.0, "market_value": 0.0, "unrealized_pnl": 0.0}

    async def get_account(self) -> dict:
        if self._trading_client is None:
            return {}
        acct = self._trading_client.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
        }

    async def close_all_positions(self) -> None:
        if self._trading_client is None:
            return
        self._trading_client.close_all_positions(cancel_orders=True)
        log.info("Closed all positions")
