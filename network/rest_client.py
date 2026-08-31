import aiohttp
from config import REST_BASE, SYMBOL, INTERVAL
from core.market_state import market_state


async def bootstrap_market_snapshot():
    async with aiohttp.ClientSession() as session:
        # 1. Fetch 15m Klines
        try:
            async with session.get(f"{REST_BASE}/fapi/v1/klines?symbol={SYMBOL}&interval={INTERVAL}&limit=200") as resp:
                if resp.status == 200:
                    raw = await resp.json()
                    market_state.klines_15m.extend([[float(x) for x in k[:6]] for k in raw])
        except Exception:
            pass

        # 2. Fetch Mark Price & Funding Rate
        try:
            async with session.get(f"{REST_BASE}/fapi/v1/premiumIndex?symbol={SYMBOL}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    market_state.mark_price = float(data.get("markPrice", 0))
                    market_state.index_price = float(data.get("indexPrice", 0))
                    market_state.funding_rate = float(data.get("lastFundingRate", 0))
                    market_state.next_funding_time = int(data.get("nextFundingTime", 0))
        except Exception:
            pass

        # 3. Fetch Open Interest
        try:
            async with session.get(f"{REST_BASE}/fapi/v1/openInterest?symbol={SYMBOL}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    market_state.open_interest = float(data.get("openInterest", 0))
        except Exception:
            pass
