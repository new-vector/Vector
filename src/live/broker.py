"""
broker.py — Abstract broker interface.

All brokers (Alpaca, IBKR, etc.) must implement this protocol.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.models import Order, OrderStatus, TradeResult


class BrokerAdapter(ABC):
    """Abstract interface for order submission and position queries."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the broker."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        ...

    @abstractmethod
    async def submit_order(self, order: Order) -> str:
        """
        Submit an order.  Returns the broker-assigned order ID.
        """
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order.  Returns True if successful."""
        ...

    @abstractmethod
    async def get_position(self, symbol: str) -> dict:
        """
        Return current position info for *symbol*.

        Expected keys: qty, avg_entry_price, market_value, unrealized_pnl
        """
        ...

    @abstractmethod
    async def get_account(self) -> dict:
        """
        Return account info.

        Expected keys: equity, cash, buying_power
        """
        ...

    @abstractmethod
    async def close_all_positions(self) -> None:
        """Flatten everything."""
        ...
