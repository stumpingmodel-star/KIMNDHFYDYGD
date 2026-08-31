import asyncio
import json
import time
import websockets
from config import WS_BASE, SYMBOL, INTERVAL
from core.market_state import market_state
from core.liquidation_engine import liquidation_engine


async def ws_trade_stream():
    url = f"{WS_BASE}/{SYMBOL.lower()}@aggTrade"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                async for msg in ws:
                    data = json.loads(msg)
                    price = float(data["p"])
                    qty = float(data["q"])
                    is_buyer_maker = data["m"]
                    recv_ms = time.time() * 1000

                    market_state.network_latency_ms = max(0.0, recv_ms - data["E"])
                    market_state.last_price = price
                    market_state.last_update_ts = time.time()

                    delta = -qty if is_buyer_maker else qty
                    market_state.cvd += delta

                    # 5-second Delta Tracking
                    now = time.time()
                    market_state.trade_events_5s.append((now, delta))
                    cutoff = now - 5.0
                    while market_state.trade_events_5s and market_state.trade_events_5s[0][0] < cutoff:
                        market_state.trade_events_5s.popleft()
                    market_state.recent_cvd_5s = sum(t[1] for t in market_state.trade_events_5s)

                    market_state.trade_tape.appendleft((now, price, qty, not is_buyer_maker))
        except Exception:
            await asyncio.sleep(1)


async def ws_depth_stream():
    url = f"{WS_BASE}/{SYMBOL.lower()}@depth20@100ms"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                async for msg in ws:
                    data = json.loads(msg)
                    market_state.bids = [(float(p), float(q)) for p, q in data.get("b", [])]
                    market_state.asks = [(float(p), float(q)) for p, q in data.get("a", [])]

                    top10_bid = sum(q for _, q in market_state.bids[:10])
                    top10_ask = sum(q for _, q in market_state.asks[:10])
                    if top10_bid + top10_ask > 0:
                        market_state.ob_imbalance = ((top10_bid - top10_ask) / (top10_bid + top10_ask)) * 100.0
        except Exception:
            await asyncio.sleep(1)


async def ws_mark_price_stream():
    url = f"{WS_BASE}/{SYMBOL.lower()}@markPrice@1s"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                async for msg in ws:
                    data = json.loads(msg)
                    market_state.mark_price = float(data.get("p", market_state.mark_price))
                    market_state.funding_rate = float(data.get("r", market_state.funding_rate))
                    market_state.next_funding_time = int(data.get("T", market_state.next_funding_time))
        except Exception:
            await asyncio.sleep(1)


async def ws_force_order_stream():
    url = f"{WS_BASE}/{SYMBOL.lower()}@forceOrder"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                async for msg in ws:
                    data = json.loads(msg)
                    o = data.get("o", {})
                    side = o.get("S")
                    qty = float(o.get("q", 0))
                    price = float(o.get("ap", o.get("p", 0)))
                    if qty > 0 and price > 0:
                        liquidation_engine.register_event(side, qty, price)
        except Exception:
            await asyncio.sleep(1)


async def ws_kline_stream():
    url = f"{WS_BASE}/{SYMBOL.lower()}@kline_{INTERVAL}"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                async for msg in ws:
                    data = json.loads(msg)
                    k = data["k"]
                    is_closed = k["x"]
                    candle = [float(k["t"]), float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])]
                    if is_closed:
                        market_state.klines_15m.append(candle)
                    elif len(market_state.klines_15m) > 0:
                        market_state.klines_15m[-1] = candle
        except Exception:
            await asyncio.sleep(1)
