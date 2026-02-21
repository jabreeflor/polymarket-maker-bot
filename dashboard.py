#!/usr/bin/env python3
"""CLI dashboard for the Polymarket maker bot paper trader."""

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timezone

import websockets
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.layout import Layout

DB_PATH = "paper_trades.db"
BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
WINDOW_SECONDS = 300

console = Console()
live_price = {"btc": 0.0}


def get_stats(con):
    cur = con.execute("SELECT value FROM state WHERE key='balance'")
    row = cur.fetchone()
    balance = float(row[0]) if row else 100.0

    trades = con.execute(
        "SELECT COUNT(*), SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN outcome='SKIP' THEN 1 ELSE 0 END), "
        "COALESCE(SUM(pnl),0) FROM trades"
    ).fetchone()

    total, wins, losses, skips, total_pnl = trades
    total = total or 0; wins = wins or 0; losses = losses or 0; skips = skips or 0
    bets = wins + losses
    win_rate = (wins / bets * 100) if bets > 0 else 0

    return {
        "balance": balance, "total": total, "wins": wins, "losses": losses,
        "skips": skips, "bets": bets, "win_rate": win_rate, "total_pnl": total_pnl,
    }


def get_recent_trades(con, n=20):
    return con.execute(
        "SELECT timestamp, direction_bet, btc_open, btc_close, outcome, pnl, balance_after "
        "FROM trades ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()


def build_display(con):
    s = get_stats(con)
    trades = get_recent_trades(con)

    # Stats panel
    pnl_color = "green" if s["total_pnl"] >= 0 else "red"
    stats_text = (
        f"[bold]Balance:[/] [cyan]${s['balance']:.2f}[/]  |  "
        f"[bold]P&L:[/] [{pnl_color}]${s['total_pnl']:+.2f}[/{pnl_color}]  |  "
        f"[bold]Win Rate:[/] [yellow]{s['win_rate']:.1f}%[/] ({s['wins']}W/{s['losses']}L/{s['skips']}S)  |  "
        f"[bold]BTC:[/] [white]${live_price['btc']:,.2f}[/]"
    )

    # Window status
    now = time.time()
    window_start = now - (now % WINDOW_SECONDS)
    window_end = window_start + WINDOW_SECONDS
    elapsed = now - window_start
    remaining = window_end - now
    bar_len = 30
    filled = int(elapsed / WINDOW_SECONDS * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    ws_start_str = datetime.fromtimestamp(window_start, tz=timezone.utc).strftime("%H:%M")
    ws_end_str = datetime.fromtimestamp(window_end, tz=timezone.utc).strftime("%H:%M")
    window_text = f"[bold]Window:[/] {ws_start_str}→{ws_end_str}  [{bar}]  {remaining:.0f}s left"
    if remaining <= 10:
        window_text += "  [bold red]⚡ SIGNAL ZONE[/]"

    # Trades table
    table = Table(title="Last 20 Trades", expand=True, border_style="dim")
    table.add_column("Time", style="dim", width=19)
    table.add_column("Dir", width=5)
    table.add_column("Open", justify="right", width=12)
    table.add_column("Close", justify="right", width=12)
    table.add_column("Result", width=6)
    table.add_column("PnL", justify="right", width=10)
    table.add_column("Balance", justify="right", width=10)

    for t in trades:
        ts, dirn, bopen, bclose, outcome, pnl, bal = t
        if outcome == "WIN":
            res_style, pnl_style = "green", "green"
        elif outcome == "LOSS":
            res_style, pnl_style = "red", "red"
        else:
            res_style, pnl_style = "dim", "dim"
        table.add_row(
            ts, dirn or "-",
            f"${bopen:,.2f}" if bopen else "-",
            f"${bclose:,.2f}" if bclose else "-",
            f"[{res_style}]{outcome}[/{res_style}]",
            f"[{pnl_style}]${pnl:+.4f}[/{pnl_style}]",
            f"${bal:.2f}",
        )

    header = Panel(f"{stats_text}\n{window_text}", title="[bold]Polymarket Maker Bot — Paper Trader[/]", border_style="blue")
    group = console.group(header, table)
    return group


async def price_loop():
    while True:
        try:
            async with websockets.connect(BINANCE_WS) as ws:
                async for msg in ws:
                    live_price["btc"] = float(json.loads(msg)["p"])
        except Exception:
            await asyncio.sleep(3)


async def dashboard_loop():
    # Give price feed a moment
    await asyncio.sleep(1)
    con = sqlite3.connect(DB_PATH)
    with Live(console=console, refresh_per_second=1) as live:
        while True:
            try:
                display = build_display(con)
                live.update(display)
            except Exception:
                pass
            await asyncio.sleep(1)


async def main():
    await asyncio.gather(price_loop(), dashboard_loop())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
