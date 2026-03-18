"""
feed.py — Live market data feed.

Polls or streams bars from Alpaca and aggregates into Candle objects
that are fed into the TradingEngine.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Callable

from src.models import Candle

log = logging.getLogger(__name__)


class AlpacaBarFeed:
    """
    Streams 1-minute bars from Alpaca and aggregates higher timeframes.

    In live mode, uses WebSocket streaming.  For simplicity this
    implementation uses polling with configurable interval.
    """

    def __init__(
        self,
        symbol: str = "SPY",
        primary_tf: str = "5m",
        poll_interval_seconds: int = 60,
        paper: bool = True,
    ) -> None:
        self.symbol = symbol
        self.primary_tf = primary_tf
        self.poll_interval = poll_interval_seconds
        self._paper = paper
        self._running = False
        self._key = os.environ.get("APCA_API_KEY_ID", "")
        self._secret = os.environ.get("APCA_API_SECRET_KEY", "")

        # Bar aggregation buffers
        self._1m_buffer: list[Candle] = []
        self._tf_minutes = _parse_tf_minutes(primary_tf)

    async def stream(self, callback: Callable[[Candle], None]) -> None:
        """
        Start polling for new bars and invoke *callback* with each
        completed candle.
        """
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        client = StockHistoricalDataClient(self._key, self._secret)
        self._running = True
        last_ts: datetime | None = None

        log.info("Feed started for %s (%s)", self.symbol, self.primary_tf)

        while self._running:
            try:
                now = datetime.now(timezone.utc)
                start = now - timedelta(minutes=self._tf_minutes + 1)

                request = StockBarsRequest(
                    symbol_or_symbols=self.symbol,
                    timeframe=TimeFrame(self._tf_minutes, TimeFrameUnit.Minute),
                    start=start,
                    end=now,
                )
                bars = client.get_stock_bars(request)
                df = bars.df

                if not df.empty:
                    if hasattr(df.index, "droplevel"):
                        try:
                            df = df.droplevel("symbol")
                        except (KeyError, ValueError):
                            pass

                    for ts, row in df.iterrows():
                        if isinstance(ts, str):
                            ts = datetime.fromisoformat(ts)
                        elif hasattr(ts, "to_pydatetime"):
                            ts = ts.to_pydatetime()

                        if last_ts is not None and ts <= last_ts:
                            continue

                        candle = Candle(
                            timestamp=ts,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row.get("volume", 0)),
                            timeframe=self.primary_tf,
                        )
                        callback(candle)
                        last_ts = ts

            except Exception as exc:
                log.error("Feed error: %s", exc)

            await asyncio.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False


def _parse_tf_minutes(tf: str) -> int:
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    return 5
