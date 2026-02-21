#!/usr/bin/env python3
"""
Polymarket Maker Bot — Paper Trader
Strategy: 5-min BTC up/down markets, enter at T-10s on the likely winning side at 92¢.
Uses real Binance WebSocket data, simulated Polymarket markets.
"""

import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone

import websockets

# ── Config ──────────────────────────────────────────────────────────────────
BINANCE_WS_ENDPOINTS = [
    "wss://stream.binance.com:9443/ws/btcusdt@trade",
    "wss://stream.binance.us:9443/ws/btcusd@trade",
]
WINDOW_SECONDS = 300          # 5 minutes
SIGNAL_OFFSET = 10            # seconds before close to evaluate
MIN_MOVE_USD = 5.0            # minimum BTC move to place a bet
ENTRY_PRICE = 0.92            # price we pay per share
ORDER_SIZE_USD = 10.0         # notional per trade
MAKER_REBATE = 0.005          # rebate per filled order
INITIAL_BALANCE = 100.0
DB_PATH = "paper_trades.db"
LOG_FILE = "bot.log"

# ── Logging ─────────────────────────────────────────────────────────────────
logger = logging.getLogger("maker-bot")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
ch = logging.StreamHandler()
ch.setFormatter(fmt)
fh = logging.FileHandler(LOG_FILE)
fh.setFormatter(fmt)
logger.addHandler(ch)
logger.addHandler(fh)

# ── Database ────────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            window_start TEXT,
            window_end TEXT,
            btc_open REAL,
            btc_at_signal REAL,
            btc_close REAL,
            direction_bet TEXT,
            entry_price REAL,
            outcome TEXT,
            pnl REAL,
            balance_after REAL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Init balance if not set
    cur = con.execute("SELECT value FROM state WHERE key='balance'")
    if cur.fetchone() is None:
        con.execute("INSERT INTO state VALUES ('balance', ?)", (str(INITIAL_BALANCE),))
    con.commit()
    return con


def get_balance(con):
    return float(con.execute("SELECT value FROM state WHERE key='balance'").fetchone()[0])


def set_balance(con, bal):
    con.execute("UPDATE state SET value=? WHERE key='balance'", (str(bal),))
    con.commit()


def record_trade(con, **kw):
    con.execute("""
        INSERT INTO trades (timestamp, window_start, window_end, btc_open,
            btc_at_signal, btc_close, direction_bet, entry_price, outcome, pnl, balance_after)
        VALUES (:timestamp, :window_start, :window_end, :btc_open,
            :btc_at_signal, :btc_close, :direction_bet, :entry_price, :outcome, :pnl, :balance_after)
    """, kw)
    con.commit()


# ── Helpers ─────────────────────────────────────────────────────────────────
def next_window_start():
    """Return epoch time of the next 5-min aligned window."""
    now = time.time()
    return now - (now % WINDOW_SECONDS) + WINDOW_SECONDS


def fmt_ts(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ── Main Loop ───────────────────────────────────────────────────────────────
async def run():
    con = init_db()
    balance = get_balance(con)
    logger.info(f"🚀 Bot started | Balance: ${balance:.2f}")

    latest_price = None

    async def price_feed():
        nonlocal latest_price
        while True:
            for endpoint in BINANCE_WS_ENDPOINTS:
                try:
                    async with websockets.connect(endpoint) as ws:
                        logger.info(f"📡 Connected to {endpoint}")
                        async for msg in ws:
                            data = json.loads(msg)
                            latest_price = float(data["p"])
                except Exception as e:
                    logger.warning(f"WS error ({endpoint}): {e}")
                    continue
            logger.info("All endpoints failed, retrying in 5s...")
            await asyncio.sleep(5)

    async def market_loop():
        nonlocal balance
        while latest_price is None:
            await asyncio.sleep(0.1)

        while True:
            # Wait for next window
            ws_epoch = next_window_start()
            wait = ws_epoch - time.time()
            if wait > 0:
                logger.info(f"⏳ Next window at {fmt_ts(ws_epoch)} (in {wait:.0f}s)")
                await asyncio.sleep(wait)

            # Window open
            btc_open = latest_price
            window_end_epoch = ws_epoch + WINDOW_SECONDS
            logger.info(f"📊 Window open | BTC: ${btc_open:,.2f}")

            # Wait until T-10s before close
            signal_time = window_end_epoch - SIGNAL_OFFSET
            wait_signal = signal_time - time.time()
            if wait_signal > 0:
                await asyncio.sleep(wait_signal)

            btc_at_signal = latest_price
            move = btc_at_signal - btc_open

            if abs(move) < MIN_MOVE_USD:
                # Skip — not enough movement
                logger.info(f"⏭️  SKIP | Move: ${move:+.2f} (< ${MIN_MOVE_USD})")
                record_trade(con,
                    timestamp=fmt_ts(time.time()),
                    window_start=fmt_ts(ws_epoch),
                    window_end=fmt_ts(window_end_epoch),
                    btc_open=btc_open,
                    btc_at_signal=btc_at_signal,
                    btc_close=btc_at_signal,
                    direction_bet="NONE",
                    entry_price=0,
                    outcome="SKIP",
                    pnl=0,
                    balance_after=balance,
                )
                # Still wait for window to close before next iteration
                remaining = window_end_epoch - time.time()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                continue

            direction = "UP" if move > 0 else "DOWN"
            shares = ORDER_SIZE_USD / ENTRY_PRICE
            logger.info(f"🎯 BET {direction} | Move: ${move:+.2f} | Entry: {ENTRY_PRICE} | Shares: {shares:.2f}")

            # Wait for resolution
            remaining = window_end_epoch - time.time()
            if remaining > 0:
                await asyncio.sleep(remaining)

            btc_close = latest_price
            actual = "UP" if btc_close > btc_open else "DOWN"

            if btc_close == btc_open:
                # Flat — count as loss for the bettor
                outcome = "LOSS"
            elif actual == direction:
                outcome = "WIN"
            else:
                outcome = "LOSS"

            if outcome == "WIN":
                profit = shares * (1.0 - ENTRY_PRICE) + MAKER_REBATE
                pnl = round(profit, 4)
            else:
                pnl = round(-ORDER_SIZE_USD + MAKER_REBATE, 4)

            balance = round(balance + pnl, 4)
            set_balance(con, balance)

            icon = "✅" if outcome == "WIN" else "❌"
            logger.info(f"{icon} {outcome} | Close: ${btc_close:,.2f} | Actual: {actual} | PnL: ${pnl:+.4f} | Bal: ${balance:.2f}")

            record_trade(con,
                timestamp=fmt_ts(time.time()),
                window_start=fmt_ts(ws_epoch),
                window_end=fmt_ts(window_end_epoch),
                btc_open=btc_open,
                btc_at_signal=btc_at_signal,
                btc_close=btc_close,
                direction_bet=direction,
                entry_price=ENTRY_PRICE,
                outcome=outcome,
                pnl=pnl,
                balance_after=balance,
            )

    await asyncio.gather(price_feed(), market_loop())


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
