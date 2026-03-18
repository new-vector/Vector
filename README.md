# Brinks Box — Hybrid System Automated Trading Engine

A production-grade Python automated trading system implementing the **Traders Reality Hybrid System (Brinks Box Strategy)** with backtesting, live trading via Alpaca, and a real-time monitoring dashboard.

## Features

- **Tick-Proxy Vector Detection** — composite scoring (volume z-score + range z-score + body fraction) across 1m/5m/15m timeframes with multi-TF confluence detection
- **Proper Recovery Tracking** — bar-by-bar tracking of partial and full vector recovery using max price penetration, not simple close-over
- **Brinks Box Builder** — session high/low/mid accumulation with Asian session range context and sweep detection
- **3 Entry Types** — reversal-to-vector, continuation breakout, and momentum entries
- **Full Filter Stack** — EMA trend, Brinks midpoint hold, news blackout, daily trade limits
- **Risk Manager** — 4 stop modes (opposite box side, box mid, ATR, invalidation) + external vector targets
- **Event-Driven Backtester** — with Sharpe, Sortino, max drawdown, profit factor, and signal-type breakdown
- **Live Trading** — Alpaca paper/live adapter with bar polling
- **Real-Time Dashboard** — dark terminal-style UI showing box levels, vectors, signals, trade journal

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Run backtest with CSV data
python scripts/backtest.py --data data/spy_5m.csv

# Run backtest with Alpaca historical data
export APCA_API_KEY_ID=your_key
export APCA_API_SECRET_KEY=your_secret
python scripts/backtest.py --symbol SPY --start 2024-01-01 --end 2024-12-31

# Run live paper trading
python scripts/live.py --paper --symbol SPY

# Run tests
python -m pytest tests/ -v
```

## Project Structure

```
Vector/
├── config/default.yaml          # Strategy parameters
├── src/
│   ├── models.py                # Data classes (VectorCandle, BrinksBox, etc.)
│   ├── config.py                # YAML config loader
│   ├── session.py               # Session window detection
│   ├── vectors.py               # Multi-TF vector engine
│   ├── brinks_box.py            # Box builder + Asian range
│   ├── signals.py               # Entry signal engine
│   ├── indicators.py            # EMA, ATR, SMA, z-scores
│   ├── risk.py                  # Stop/target/sizing
│   ├── portfolio.py             # Position tracking + journal
│   ├── news.py                  # Economic calendar filter
│   ├── engine.py                # Main orchestrator
│   ├── backtest/                # Backtesting engine
│   ├── live/                    # Alpaca adapter + feed
│   └── dashboard/               # FastAPI + real-time UI
├── scripts/
│   ├── backtest.py              # CLI: run backtest
│   └── live.py                  # CLI: run live/paper
└── tests/                       # Unit + integration tests
```

## Configuration

All parameters in `config/default.yaml`. Key sections:

| Section | Controls |
|---|---|
| `session` | Timezone, Brinks/trade/Asian session times |
| `vectors` | Lookback, thresholds, body fraction, max age, timeframes |
| `trade_logic` | Entry types enabled, EMA lengths, mid-hold filter |
| `risk` | Stop mode, ATR params, R:R target, daily limits |
| `news` | Blackout window, impact levels |
| `backtest` | Initial capital, commission, min trades target |
| `live` | Broker, paper mode, position sizing |