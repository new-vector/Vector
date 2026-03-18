"""
data_loader.py — Historical OHLCV data loaders.

Supports:
  - CSV files (datetime, open, high, low, close, volume)
  - Alpaca historical bars via REST API
  - Multi-timeframe loading (1m, 5m, 15m) with chronological merge
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Sequence

import pandas as pd

from src.models import Candle

log = logging.getLogger(__name__)


# ── CSV Loader ───────────────────────────────────────────────────────────

def load_csv(
    path: str | Path,
    timeframe: str = "5m",
    date_col: str = "datetime",
    date_format: str | None = None,
) -> list[Candle]:
    """
    Load OHLCV from a CSV file.

    Expected columns (case-insensitive):
      datetime (or date/time/timestamp), open, high, low, close, volume

    Returns a list of ``Candle`` sorted by timestamp.
    """
    path = Path(path)
    df = pd.read_csv(path)

    # Normalise column names
    df.columns = [c.strip().lower() for c in df.columns]

    # Find the date column
    for candidate in [date_col.lower(), "datetime", "date", "time", "timestamp"]:
        if candidate in df.columns:
            df["_ts"] = pd.to_datetime(df[candidate], format=date_format)
            break
    else:
        raise ValueError(f"Cannot find a date column in {list(df.columns)}")

    df.sort_values("_ts", inplace=True)
    df.reset_index(drop=True, inplace=True)

    candles: list[Candle] = []
    for idx, row in df.iterrows():
        candles.append(Candle(
            timestamp=row["_ts"].to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
            bar_index=0,
            timeframe=timeframe,
        ))

    log.info("Loaded %d bars from %s (%s)", len(candles), path.name, timeframe)
    return candles


# ── Alpaca Historical Loader ─────────────────────────────────────────────

def load_alpaca(
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe: str = "5m",
    api_key: str | None = None,
    api_secret: str | None = None,
    paper: bool = True,
) -> list[Candle]:
    """
    Fetch historical bars from Alpaca Markets.

    Requires ``alpaca-py`` and valid API credentials (via params or
    APCA_API_KEY_ID / APCA_API_SECRET_KEY environment variables).
    """
    import os
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    key = api_key or os.environ.get("APCA_API_KEY_ID", "")
    secret = api_secret or os.environ.get("APCA_API_SECRET_KEY", "")

    client = StockHistoricalDataClient(key, secret)

    tf_map = {
        "1m": TimeFrame(1, TimeFrameUnit.Minute),
        "5m": TimeFrame(5, TimeFrameUnit.Minute),
        "15m": TimeFrame(15, TimeFrameUnit.Minute),
        "1h": TimeFrame(1, TimeFrameUnit.Hour),
        "1d": TimeFrame(1, TimeFrameUnit.Day),
    }
    alpaca_tf = tf_map.get(timeframe)
    if alpaca_tf is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=alpaca_tf,
        start=start,
        end=end,
    )
    bars = client.get_stock_bars(request)
    df = bars.df

    if df.empty:
        log.warning("No bars returned for %s %s–%s", symbol, start, end)
        return []

    # Reset multi-index if present
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()

    candles: list[Candle] = []
    for _, row in df.iterrows():
        ts = row.get("timestamp", row.name)
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        candles.append(Candle(
            timestamp=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
            bar_index=0,
            timeframe=timeframe,
        ))

    candles.sort(key=lambda c: c.timestamp)
    log.info("Loaded %d bars for %s from Alpaca (%s)", len(candles), symbol, timeframe)
    return candles


# ── Multi-Timeframe Merge ────────────────────────────────────────────────

def merge_multi_timeframe(
    *bar_lists: list[Candle],
) -> list[Candle]:
    """
    Merge multiple timeframe bar lists into one chronologically sorted
    sequence.  Within the same timestamp, lower timeframes come first.
    """
    tf_order = {"1m": 0, "5m": 1, "15m": 2, "1h": 3, "1d": 4}
    all_bars: list[Candle] = []
    for bl in bar_lists:
        all_bars.extend(bl)
    all_bars.sort(key=lambda c: (c.timestamp, tf_order.get(c.timeframe, 99)))
    return all_bars
