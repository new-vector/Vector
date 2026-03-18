"""
config.py — YAML → typed dataclass config loader.

Loads ``config/default.yaml`` and merges with any overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ── Section dataclasses ──────────────────────────────────────────────────

@dataclass
class SessionConfig:
    timezone: str = "America/New_York"
    brinks_start: str = "09:00"
    brinks_end: str = "10:00"
    trade_window_start: str = "10:00"
    trade_window_end: str = "12:00"
    asian_session_start: str = "00:00"
    asian_session_end: str = "08:00"
    weekdays_only: bool = True


@dataclass
class VectorConfig:
    lookback: int = 20
    primary_threshold: float = 2.0
    secondary_threshold: float = 1.5
    body_fraction_min: float = 0.45
    max_external_age_bars: int = 24
    timeframes: list[str] = field(default_factory=lambda: ["1m", "5m", "15m"])
    primary_timeframe: str = "5m"


@dataclass
class TradeLogicConfig:
    allow_reversal: bool = True
    allow_continuation: bool = True
    allow_momentum_entry: bool = True
    require_mid_hold: bool = True
    use_ema_filter: bool = True
    ema_fast: int = 13
    ema_slow: int = 50
    track_all_internal_vectors: bool = True


@dataclass
class RiskConfig:
    stop_mode: str = "opposite_box_side"
    atr_length: int = 14
    atr_multiplier: float = 1.2
    rr_target: float = 1.5
    buffer_ticks: int = 2
    one_trade_per_day: bool = True
    flatten_after_window: bool = True
    time_at_entry_max_bars: int = 10


@dataclass
class NewsConfig:
    enabled: bool = True
    blackout_minutes_before: int = 15
    blackout_minutes_after: int = 15
    impact_levels: list[str] = field(default_factory=lambda: ["high"])


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    commission_pct: float = 0.04
    default_symbol: str = "SPY"
    min_trades_wanted: int = 50


@dataclass
class LiveConfig:
    broker: str = "alpaca"
    paper_trading: bool = True
    symbol: str = "SPY"
    position_size_mode: str = "fixed_shares"
    fixed_shares: int = 100
    max_equity_pct: float = 0.10


# ── Root config ──────────────────────────────────────────────────────────

@dataclass
class SystemConfig:
    session: SessionConfig = field(default_factory=SessionConfig)
    vectors: VectorConfig = field(default_factory=VectorConfig)
    trade_logic: TradeLogicConfig = field(default_factory=TradeLogicConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    live: LiveConfig = field(default_factory=LiveConfig)


# ── Loader ───────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _dict_to_dataclass(cls: type, data: dict[str, Any]) -> Any:
    """Construct a dataclass *cls* from *data*, ignoring unknown keys."""
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(cls)}
    filtered = {k: v for k, v in data.items() if k in field_names}
    return cls(**filtered)


def load_config(
    path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> SystemConfig:
    """
    Load the YAML config file, apply optional overrides, and return a
    fully-typed ``SystemConfig``.

    If *path* is ``None``, looks for ``config/default.yaml`` relative to
    the project root (two levels up from this file).
    """
    if path is None:
        project_root = Path(__file__).resolve().parent.parent
        path = project_root / "config" / "default.yaml"
    else:
        path = Path(path)

    raw: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

    if overrides:
        raw = _deep_merge(raw, overrides)

    return SystemConfig(
        session=_dict_to_dataclass(SessionConfig, raw.get("session", {})),
        vectors=_dict_to_dataclass(VectorConfig, raw.get("vectors", {})),
        trade_logic=_dict_to_dataclass(TradeLogicConfig, raw.get("trade_logic", {})),
        risk=_dict_to_dataclass(RiskConfig, raw.get("risk", {})),
        news=_dict_to_dataclass(NewsConfig, raw.get("news", {})),
        backtest=_dict_to_dataclass(BacktestConfig, raw.get("backtest", {})),
        live=_dict_to_dataclass(LiveConfig, raw.get("live", {})),
    )
