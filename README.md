# Polymarket Maker Bot — Paper Trader

Paper trading bot that validates a market-making strategy on Polymarket's 5-minute BTC up/down markets.

## The Strategy

Based on [@_dominatos's analysis](https://twitter.com/_dominatos):

- Polymarket runs **288 binary markets per day** — "Will BTC go up or down in the next 5 minutes?"
- At **T-10 seconds** before a window closes, BTC's direction is ~85% determined but odds haven't fully adjusted
- Post a **maker order** on the winning side at **92¢**
- Win → resolve at $1.00 = **$0.08/share profit** + maker rebate
- Loss → resolve at $0.00 = **-$0.92/share loss**
- Makers pay **zero fees** and earn daily USDC rebates
- Break-even win rate: ~92% — strategy claims ~85% signal accuracy

## How It Works

- **Real data**: Live BTC prices via Binance WebSocket
- **Simulated markets**: Every 5 minutes (aligned to clock), a new market opens
- At T-10s, if BTC moved > $5 from open, we bet on the current direction at 92¢
- At window close, market resolves based on actual price vs open
- All trades logged to SQLite + console + file

## Quick Start

```bash
pip install -r requirements.txt

# Run the bot (foreground)
python bot.py

# Or run in background
chmod +x start.sh stop.sh
./start.sh

# View dashboard (separate terminal)
python dashboard.py

# Stop background bot
./stop.sh
```

## Files

| File | Purpose |
|------|---------|
| `bot.py` | Main bot — connects to Binance, runs market loop |
| `dashboard.py` | Rich CLI dashboard — stats, trades, live price |
| `paper_trades.db` | SQLite database (auto-created) |
| `bot.log` | Log file |

## Config (in bot.py)

| Param | Default | Description |
|-------|---------|-------------|
| `ENTRY_PRICE` | 0.92 | Price per share |
| `ORDER_SIZE_USD` | 10 | Notional per trade |
| `MIN_MOVE_USD` | 5.0 | Min BTC move to trigger bet |
| `MAKER_REBATE` | 0.005 | Rebate per filled order |
| `INITIAL_BALANCE` | 100.0 | Starting paper balance |

## What to Watch For

Run for a few days and check:
- **Win rate** — need ~92%+ to be profitable at 92¢ entry
- **Skip rate** — how many windows are "unclear"
- **P&L curve** — is it trending up or down?
- **Edge decay** — does the signal degrade over time?
