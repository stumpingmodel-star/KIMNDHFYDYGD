import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sys
sys.path.append(str(Path(__file__).parent.parent))

from config import INTERVAL, SYMBOL, PRICE_DECIMALS, QTY_DECIMALS
from core.indicators import QuantitativeEngine
from core.liquidation_engine import liquidation_engine
from core.market_state import market_state
from core.scalp_engine import scalp_engine
from execution.trade_manager import trade_executor
from network.rest_client import bootstrap_market_snapshot
from network.rest_polling import (
    poll_klines,
    poll_mark_price,
    poll_open_interest,
    poll_trades,
)
from network.streams import (
    ws_depth_stream,
    ws_force_order_stream,
    ws_kline_stream,
    ws_mark_price_stream,
    ws_trade_stream,
)


BASE_DIR = Path(__file__).parent
clients: set[WebSocket] = set()


def _ts_to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def _format_price(value: float) -> str:
    return f"${value:,.{PRICE_DECIMALS}f}"


def _format_qty(value: float) -> str:
    return f"{value:.{QTY_DECIMALS}f}"


def _build_snapshot() -> dict:
    closes = [k[4] for k in market_state.klines_15m] if market_state.klines_15m else [market_state.last_price or 0.0]
    highs = [k[2] for k in market_state.klines_15m] if market_state.klines_15m else [market_state.last_price or 0.0]
    lows = [k[3] for k in market_state.klines_15m] if market_state.klines_15m else [market_state.last_price or 0.0]

    rsi = QuantitativeEngine.calculate_rsi(closes)
    atr = QuantitativeEngine.calculate_atr(closes, highs, lows)
    vwap = QuantitativeEngine.calculate_vwap(market_state.klines_15m)
    ema_9 = QuantitativeEngine.calculate_ema(closes, 9)
    ema_21 = QuantitativeEngine.calculate_ema(closes, 21)
    micro_price = QuantitativeEngine.calculate_micro_price(market_state.bids, market_state.asks)

    direction = "LONG" if market_state.last_price > ema_9 and rsi < 60 else "SHORT" if market_state.last_price < ema_9 and rsi > 40 else "NEUTRAL"
    liq_stats = liquidation_engine.update(market_state.last_price, market_state.recent_cvd_5s)
    scalp_signal = scalp_engine.generate_signal()

    return {
        "type": "snapshot",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "latency_ms": round(market_state.network_latency_ms, 1),
        "last_price": market_state.last_price,
        "mark_price": market_state.mark_price,
        "micro_price": micro_price,
        "index_price": market_state.index_price,
        "funding_rate": market_state.funding_rate,
        "open_interest": market_state.open_interest,
        "ob_imbalance": market_state.ob_imbalance,
        "cvd": market_state.cvd,
        "recent_cvd_5s": market_state.recent_cvd_5s,
        "rsi": round(rsi, 1),
        "atr": round(atr, PRICE_DECIMALS),
        "vwap": round(vwap, PRICE_DECIMALS),
        "ema_9": round(ema_9, PRICE_DECIMALS),
        "ema_21": round(ema_21, PRICE_DECIMALS),
        "direction": direction,
        "scalp_signal": scalp_signal,
        "liq_state": liq_stats["state"],
        "liq_side": liq_stats["side"],
        "liq_velocity": round(liq_stats["velocity"], 2),
        "liq_peak_velocity": round(liq_stats["peak_velocity"], 2),
        "liq_long_10s": round(liq_stats["long_10s"], 2),
        "liq_short_10s": round(liq_stats["short_10s"], 2),
        "liq_wick_extreme": round(liq_stats["wick_extreme"], PRICE_DECIMALS),
        "bids": market_state.bids[:10],
        "asks": market_state.asks[:10],
        "tape": [
            {"time": _ts_to_iso(ts), "price": px, "qty": qty, "side": "BUY" if is_buy else "SELL"}
            for ts, px, qty, is_buy in list(market_state.trade_tape)[:12]
        ],
        "klines": [
            {
                "time": int(k[0] / 1000),
                "open": k[1],
                "high": k[2],
                "low": k[3],
                "close": k[4],
                "volume": k[5]
            }
            for k in market_state.klines_15m
        ]
    }


async def _broadcast_loop():
    while True:
        if clients:
            payload = _build_snapshot()
            disconnected = []
            for client in clients:
                try:
                    await client.send_text(json.dumps(payload))
                except Exception:
                    disconnected.append(client)
            for client in disconnected:
                clients.discard(client)
        await asyncio.sleep(0.1)


async def _strategy_loop():
    while True:
        if market_state.last_price > 0:
            liq_stats = liquidation_engine.update(market_state.last_price, market_state.recent_cvd_5s)
            action = liq_stats["action"]
            if action in ["BUY_CAPITULATION", "SELL_SQUEEZE"]:
                side = "BUY" if action == "BUY_CAPITULATION" else "SELL"
                wick = liq_stats["wick_extreme"]
                entry = market_state.last_price
                if side == "BUY":
                    sl = wick - 2.0
                    qty, dist = trade_executor.calculate_position_parameters(entry, sl)
                    tp1 = entry + (dist * 1.5)
                    tp2 = entry + (dist * 3.0)
                else:
                    sl = wick + 2.0
                    qty, dist = trade_executor.calculate_position_parameters(entry, sl)
                    tp1 = entry - (dist * 1.5)
                    tp2 = entry - (dist * 3.0)
                await trade_executor.execute_bracket(side, qty, sl, tp1, tp2)
        await asyncio.sleep(0.05)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bootstrap_market_snapshot()
    # WebSocket feeds (depth works in all environments; others fall back to REST polling)
    asyncio.create_task(ws_trade_stream())
    asyncio.create_task(ws_depth_stream())
    asyncio.create_task(ws_mark_price_stream())
    asyncio.create_task(ws_force_order_stream())
    asyncio.create_task(ws_kline_stream())
    # REST polling fallbacks ensure chart/price/tape keep updating if WS is blocked
    asyncio.create_task(poll_trades(interval_sec=2.0))
    asyncio.create_task(poll_klines(interval_sec=15.0))
    asyncio.create_task(poll_mark_price(interval_sec=5.0))
    asyncio.create_task(poll_open_interest(interval_sec=10.0))
    asyncio.create_task(_strategy_loop())
    asyncio.create_task(_broadcast_loop())
    yield


app = FastAPI(title=f"{SYMBOL} {INTERVAL} Scalp Terminal", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "symbol": SYMBOL,
        "interval": INTERVAL,
    })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        await websocket.send_text(json.dumps(_build_snapshot()))
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "trade":
                    side = msg.get("side", "BUY")
                    entry = market_state.last_price
                    sl = entry - 2.0 if side == "BUY" else entry + 2.0
                    qty, dist = trade_executor.calculate_position_parameters(entry, sl)
                    tp1 = entry + (dist * 1.5) if side == "BUY" else entry - (dist * 1.5)
                    tp2 = entry + (dist * 3.0) if side == "BUY" else entry - (dist * 3.0)
                    result = await trade_executor.execute_bracket(side, qty, sl, tp1, tp2)
                    await websocket.send_text(json.dumps({"type": "trade_result", "data": result}))
            except Exception as e:
                await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
    except WebSocketDisconnect:
        clients.discard(websocket)


@app.post("/trade")
async def trade_endpoint(side: str, qty: float | None = None):
    entry = market_state.last_price
    if entry <= 0:
        return {"error": "No live price available"}
    sl = entry - 2.0 if side.upper() == "BUY" else entry + 2.0
    if qty is None:
        qty, dist = trade_executor.calculate_position_parameters(entry, sl)
    else:
        dist = abs(entry - sl)
    tp1 = entry + (dist * 1.5) if side.upper() == "BUY" else entry - (dist * 1.5)
    tp2 = entry + (dist * 3.0) if side.upper() == "BUY" else entry - (dist * 3.0)
    result = await trade_executor.execute_bracket(side.upper(), qty, sl, tp1, tp2)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host="127.0.0.1", port=8080, reload=False)
