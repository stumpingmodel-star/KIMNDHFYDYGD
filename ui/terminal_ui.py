from datetime import datetime, timezone
import numpy as np
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import INTERVAL, PRICE_DECIMALS, QTY_DECIMALS
from core.indicators import QuantitativeEngine
from core.liquidation_engine import liquidation_engine
from core.market_state import market_state


def _fmt_price(value: float) -> str:
    return f"${value:,.{PRICE_DECIMALS}f}"


def _fmt_price_no_symbol(value: float) -> str:
    return f"{value:,.{PRICE_DECIMALS}f}"


def _fmt_qty(value: float) -> str:
    return f"{value:.{QTY_DECIMALS}f}"


def _render_sparkline(values, width=50):
    if len(values) < 2:
        return Text("Waiting for price data...", style="dim")
    vals = list(values)[-width:]
    min_v = min(vals)
    max_v = max(vals)
    if max_v == min_v:
        return Text("─" * len(vals), style="dim")
    blocks = "▁▂▃▄▅▆▇█"
    scaled = [int((v - min_v) / (max_v - min_v) * (len(blocks) - 1)) for v in vals]
    spark = "".join(blocks[s] for s in scaled)
    return Text(f"{spark}\nHigh: {_fmt_price(max_v)}  Low: {_fmt_price(min_v)}  Last: {_fmt_price(vals[-1])}", style="bold cyan")


def render_bloomberg_dashboard() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3)
    )
    layout["main"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1)
    )
    layout["left"].split_column(
        Layout(name="orderbook", ratio=1),
        Layout(name="tape", ratio=1)
    )
    layout["right"].split_column(
        Layout(name="chart", ratio=1),
        Layout(name="signal_hud", ratio=1),
        Layout(name="liquidation_hud", ratio=1)
    )

    # 1. Header
    utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    header_panel = Panel(
        Text(f" 🪙 BLOOMBERG XAU SCALP TERMINAL | LIVE USDⓈ-M | {INTERVAL} | UTC: {utc_str} | LATENCY: {market_state.network_latency_ms:.1f}ms ", style="bold white on dark_blue"),
        style="dark_blue"
    )
    layout["header"].update(header_panel)

    # Calculate indicators
    closes = np.array([k[4] for k in market_state.klines_15m]) if len(market_state.klines_15m) > 1 else np.array([market_state.last_price])
    highs = np.array([k[2] for k in market_state.klines_15m]) if len(market_state.klines_15m) > 1 else np.array([market_state.last_price])
    lows = np.array([k[3] for k in market_state.klines_15m]) if len(market_state.klines_15m) > 1 else np.array([market_state.last_price])

    rsi = QuantitativeEngine.calculate_rsi(closes)
    atr = QuantitativeEngine.calculate_atr(closes, highs, lows)
    vwap = QuantitativeEngine.calculate_vwap(market_state.klines_15m)
    ema_9 = QuantitativeEngine.calculate_ema(closes, 9)
    ema_21 = QuantitativeEngine.calculate_ema(closes, 21)
    micro_price = QuantitativeEngine.calculate_micro_price(market_state.bids, market_state.asks)

    # 2. Price Chart (Sparkline)
    layout["chart"].update(Panel(_render_sparkline(closes), title="[bold yellow]📈 XAU PRICE CHART (15m Closes)[/bold yellow]", border_style="yellow"))

    # 3. L2 Order Book
    ob_table = Table(expand=True, box=None, padding=(0, 1))
    ob_table.add_column("Bid Size", justify="right", style="green")
    ob_table.add_column("Bid Price", justify="right", style="bold green")
    ob_table.add_column("Ask Price", justify="left", style="bold red")
    ob_table.add_column("Ask Size", justify="left", style="red")

    b_sub = market_state.bids[:6]
    a_sub = market_state.asks[:6]
    for i in range(max(len(b_sub), len(a_sub))):
        bq = _fmt_qty(b_sub[i][1]) if i < len(b_sub) else ""
        bp = _fmt_price(b_sub[i][0]) if i < len(b_sub) else ""
        ap = _fmt_price(a_sub[i][0]) if i < len(a_sub) else ""
        aq = _fmt_qty(a_sub[i][1]) if i < len(a_sub) else ""
        ob_table.add_row(bq, bp, ap, aq)

    layout["orderbook"].update(Panel(ob_table, title=f"[bold cyan]L2 ORDER BOOK (Imbalance: {market_state.ob_imbalance:+.1f}%)[/bold cyan]", border_style="cyan"))

    # 4. Trade Tape
    tape_table = Table(expand=True, box=None, padding=(0, 1))
    tape_table.add_column("Time", style="dim")
    tape_table.add_column("Side")
    tape_table.add_column("Price", justify="right")
    tape_table.add_column("Size", justify="right")

    for ts, px, qty, is_buy in list(market_state.trade_tape)[:6]:
        side_lbl = "[bold green]BUY[/bold green]" if is_buy else "[bold red]SELL[/bold red]"
        tape_table.add_row(datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S"), side_lbl, _fmt_price(px), _fmt_qty(qty))

    layout["tape"].update(Panel(tape_table, title="[bold white]AGGREGATED TRADE TAPE[/bold white]", border_style="white"))

    # 5. Signal HUD
    sig_table = Table(expand=True, box=None, padding=(0, 1))
    sig_table.add_column("Metric", style="bold")
    sig_table.add_column("Value", justify="right")

    sig_table.add_row("XAU Price / Micro-Price", f"{_fmt_price(market_state.last_price)} / {_fmt_price(micro_price)}")
    sig_table.add_row("RSI (14) / ATR (14)", f"{rsi:.1f} / {_fmt_price(atr)}")
    sig_table.add_row("VWAP / EMA 9 / EMA 21", f"{_fmt_price(vwap)} | {_fmt_price(ema_9)} | {_fmt_price(ema_21)}")
    sig_table.add_row("5s CVD / Total CVD", f"{market_state.recent_cvd_5s:+.3f} XAU / {market_state.cvd:+.2f} XAU")
    sig_table.add_row("Funding (8h)", f"{market_state.funding_rate * 100:+.4f}%")
    sig_table.add_row("Open Interest", f"{market_state.open_interest:,.0f} XAU")

    direction = "LONG" if market_state.last_price > ema_9 and rsi < 60 else "SHORT" if market_state.last_price < ema_9 and rsi > 40 else "NEUTRAL"
    sig_color = "green" if direction == "LONG" else "red" if direction == "SHORT" else "yellow"

    layout["signal_hud"].update(Panel(sig_table, title=f"[bold {sig_color}]SCALP RADAR: {direction}[/bold {sig_color}]", border_style=sig_color))

    # 6. Liquidation Engine HUD
    liq_stats = liquidation_engine.update(market_state.last_price, market_state.recent_cvd_5s)
    liq_table = Table(expand=True, box=None, padding=(0, 1))
    liq_table.add_column("Window", style="dim")
    liq_table.add_column("Forced Sells", justify="right", style="bold red")
    liq_table.add_column("Forced Buys", justify="right", style="bold green")

    liq_table.add_row("10s Burst", f"${_fmt_price_no_symbol(liq_stats['long_10s'])}", f"${_fmt_price_no_symbol(liq_stats['short_10s'])}")
    liq_table.add_row("Liq Velocity", f"${_fmt_price_no_symbol(liq_stats['velocity'])}/s", f"Peak: ${_fmt_price_no_symbol(liq_stats['peak_velocity'])}/s")
    liq_table.add_row("Engine State", f"[bold yellow]{liq_stats['state']}[/bold yellow]", f"Wick: {_fmt_price(liq_stats['wick_extreme'])}")

    layout["liquidation_hud"].update(Panel(liq_table, title="[bold magenta]⚡ LIQUIDATION CASCADE MONITOR[/bold magenta]", border_style="magenta"))

    # 6. Footer
    layout["footer"].update(Panel(
        Text(" BINANCE WEBSOCKETS ACTIVE | 100% REAL-TIME EXCHANGE FEEDS | ZERO POLLING JITTER | PRESS CTRL+C TO EXIT ", style="black on green"),
        style="green"
    ))

    return layout
