import asyncio
import time
import aiohttp
from collections import deque
from config import REST_BASE, SYMBOL, INTERVAL
from core.market_state import market_state


async def _fetch_json(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception:
        pass
    return None


async def poll_trades(interval_sec=2.0):
    """Poll recent aggregated trades via REST (fallback when WS aggTrade is unavailable)."""
    async with aiohttp.ClientSession() as session:
        seen_trade_ids = set()
        while True:
            try:
                url = f"{REST_BASE}/fapi/v1/aggTrades?symbol={SYMBOL}&limit=50"
                data = await _fetch_json(session, url)
                if data and isinstance(data, list):
                    new_trades = []
                    for t in sorted(data, key=lambda x: x.get('T', 0)):
                        tid = t.get('a')
                        if tid in seen_trade_ids:
                            continue
                        seen_trade_ids.add(tid)
                        if len(seen_trade_ids) > 200:
                            seen_trade_ids.pop()
                        price = float(t.get('p', 0))
                        qty = float(t.get('q', 0))
                        is_buyer_maker = t.get('m', False)
                        ts = t.get('T', 0) / 1000.0
                        new_trades.append((ts, price, qty, not is_buyer_maker))

                        # Update CVD and last price
                        delta = -qty if is_buyer_maker else qty
                        market_state.cvd += delta
                        market_state.last_price = price
                        market_state.last_update_ts = time.time()

                        # 5-second delta tracking
                        now = time.time()
                        market_state.trade_events_5s.append((now, delta))
                        cutoff = now - 5.0
                        while market_state.trade_events_5s and market_state.trade_events_5s[0][0] < cutoff:
                            market_state.trade_events_5s.popleft()
                        market_state.recent_cvd_5s = sum(x[1] for x in market_state.trade_events_5s)

                    # Add newest trades to tape (already sorted oldest->newest)
                    for trade in new_trades:
                        market_state.trade_tape.appendleft(trade)
            except Exception:
                pass
            await asyncio.sleep(interval_sec)


async def poll_klines(interval_sec=15.0):
    """Poll 15m klines via REST (fallback when WS kline is unavailable)."""
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                url = f"{REST_BASE}/fapi/v1/klines?symbol={SYMBOL}&interval={INTERVAL}&limit=200"
                data = await _fetch_json(session, url)
                if data and isinstance(data, list):
                    market_state.klines_15m.clear()
                    market_state.klines_15m.extend([[float(x) for x in k[:6]] for k in data])
            except Exception:
                pass
            await asyncio.sleep(interval_sec)


async def poll_mark_price(interval_sec=5.0):
    """Poll mark price and funding via REST."""
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                url = f"{REST_BASE}/fapi/v1/premiumIndex?symbol={SYMBOL}"
                data = await _fetch_json(session, url)
                if data:
                    market_state.mark_price = float(data.get('markPrice', market_state.mark_price))
                    market_state.index_price = float(data.get('indexPrice', market_state.index_price))
                    market_state.funding_rate = float(data.get('lastFundingRate', market_state.funding_rate))
                    market_state.next_funding_time = int(data.get('nextFundingTime', market_state.next_funding_time))
            except Exception:
                pass
            await asyncio.sleep(interval_sec)


async def poll_open_interest(interval_sec=10.0):
    """Poll open interest via REST."""
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                url = f"{REST_BASE}/fapi/v1/openInterest?symbol={SYMBOL}"
                data = await _fetch_json(session, url)
                if data:
                    market_state.open_interest = float(data.get('openInterest', market_state.open_interest))
            except Exception:
                pass
            await asyncio.sleep(interval_sec)
