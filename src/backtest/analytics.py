"""
analytics.py — Backtest performance metrics.

Computes Sharpe, Sortino, max drawdown, win rate, profit factor,
average trade, R-multiple distribution, and prints a formatted summary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from src.models import PortfolioSnapshot, SignalType, TradeResult


@dataclass
class BacktestReport:
    """Full performance report from a backtest run."""

    # Summary
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    win_rate: float = 0.0

    # PnL
    total_pnl: float = 0.0
    total_commission: float = 0.0
    net_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    profit_factor: float = 0.0

    # Risk
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0

    # Time
    avg_bars_held: float = 0.0
    elapsed_seconds: float = 0.0

    # Minimums
    min_trades_wanted: int = 0
    enough_trades: bool = False

    # By signal type breakdown
    by_signal_type: dict[str, dict] = field(default_factory=dict)

    # Equity curve (for charting)
    equity_timestamps: list[str] = field(default_factory=list)
    equity_values: list[float] = field(default_factory=list)

    def print_summary(self) -> None:
        """Print a formatted summary table to stdout."""
        sep = "─" * 50
        print(f"\n{sep}")
        print("  BRINKS BOX BACKTEST RESULTS")
        print(sep)
        print(f"  Total Trades:      {self.total_trades}")
        print(f"  Winning:           {self.winning_trades}  ({self.win_rate:.1%})")
        print(f"  Losing:            {self.losing_trades}")
        print(f"  Breakeven:         {self.breakeven_trades}")
        print(sep)
        print(f"  Net PnL:           ${self.net_pnl:,.2f}")
        print(f"  Gross PnL:         ${self.total_pnl:,.2f}")
        print(f"  Commission:        ${self.total_commission:,.2f}")
        print(f"  Avg Win:           ${self.avg_win:,.2f}")
        print(f"  Avg Loss:          ${self.avg_loss:,.2f}")
        print(f"  Largest Win:       ${self.largest_win:,.2f}")
        print(f"  Largest Loss:      ${self.largest_loss:,.2f}")
        print(f"  Profit Factor:     {self.profit_factor:.2f}")
        print(sep)
        print(f"  Max Drawdown:      ${self.max_drawdown:,.2f}  ({self.max_drawdown_pct:.1%})")
        print(f"  Sharpe Ratio:      {self.sharpe_ratio:.2f}")
        print(f"  Sortino Ratio:     {self.sortino_ratio:.2f}")
        print(f"  Avg Bars Held:     {self.avg_bars_held:.1f}")
        print(sep)
        print(f"  Min Trades Target: {self.min_trades_wanted}")
        print(f"  Status:            {'✅ OK' if self.enough_trades else '⚠️ NOT ENOUGH TRADES'}")
        print(f"  Elapsed:           {self.elapsed_seconds:.2f}s")
        print(sep)

        if self.by_signal_type:
            print("\n  BY SIGNAL TYPE:")
            for stype, stats in self.by_signal_type.items():
                print(f"    {stype}: {stats['count']} trades  "
                      f"wr={stats['win_rate']:.0%}  "
                      f"pnl=${stats['net_pnl']:,.2f}")
        print()


# ── Computation ──────────────────────────────────────────────────────────

def compute_analytics(
    trades: Sequence[TradeResult],
    equity_curve: Sequence[PortfolioSnapshot],
    initial_capital: float,
    min_trades_wanted: int,
    elapsed_seconds: float,
) -> BacktestReport:
    """Compute all analytics from raw trade and equity data."""

    report = BacktestReport(
        min_trades_wanted=min_trades_wanted,
        elapsed_seconds=elapsed_seconds,
    )

    if not trades:
        return report

    report.total_trades = len(trades)
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl < 0]
    even = [t for t in trades if t.net_pnl == 0]

    report.winning_trades = len(wins)
    report.losing_trades = len(losses)
    report.breakeven_trades = len(even)
    report.win_rate = len(wins) / len(trades) if trades else 0.0

    report.total_pnl = sum(t.pnl for t in trades)
    report.total_commission = sum(t.commission for t in trades)
    report.net_pnl = sum(t.net_pnl for t in trades)

    report.avg_win = sum(t.net_pnl for t in wins) / len(wins) if wins else 0.0
    report.avg_loss = sum(t.net_pnl for t in losses) / len(losses) if losses else 0.0

    report.largest_win = max((t.net_pnl for t in wins), default=0.0)
    report.largest_loss = min((t.net_pnl for t in losses), default=0.0)

    gross_profits = sum(t.net_pnl for t in wins)
    gross_losses = abs(sum(t.net_pnl for t in losses))
    report.profit_factor = gross_profits / gross_losses if gross_losses > 0 else float("inf")

    report.avg_bars_held = sum(t.bars_held for t in trades) / len(trades) if trades else 0.0

    # ── Drawdown ─────────────────────────────────────────────────────
    if equity_curve:
        equities = [s.equity for s in equity_curve]
        peak = equities[0]
        max_dd = 0.0
        max_dd_pct = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = peak - eq
            dd_pct = dd / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
        report.max_drawdown = max_dd
        report.max_drawdown_pct = max_dd_pct

        report.equity_timestamps = [s.timestamp.isoformat() for s in equity_curve[-500:]]
        report.equity_values = [s.equity for s in equity_curve[-500:]]

    # ── Sharpe / Sortino ─────────────────────────────────────────────
    returns = [t.net_pnl for t in trades]
    if len(returns) > 1:
        mean_ret = sum(returns) / len(returns)
        std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1))
        report.sharpe_ratio = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0.0

        downside = [r for r in returns if r < 0]
        if downside:
            downside_std = math.sqrt(sum(r ** 2 for r in downside) / len(downside))
            report.sortino_ratio = (mean_ret / downside_std * math.sqrt(252)) if downside_std > 0 else 0.0

    # ── By signal type ───────────────────────────────────────────────
    type_groups: dict[str, list[TradeResult]] = {}
    for t in trades:
        key = t.signal_type.name if t.signal_type else "UNKNOWN"
        type_groups.setdefault(key, []).append(t)

    for stype, group in type_groups.items():
        w = [t for t in group if t.net_pnl > 0]
        report.by_signal_type[stype] = {
            "count": len(group),
            "win_rate": len(w) / len(group),
            "net_pnl": sum(t.net_pnl for t in group),
            "avg_pnl": sum(t.net_pnl for t in group) / len(group),
        }

    report.enough_trades = report.total_trades >= min_trades_wanted
    return report
