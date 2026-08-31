import hashlib
import hmac
import time
import urllib.parse
import aiohttp
from config import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    REST_BASE,
    SYMBOL,
    EQUITY_USD,
    RISK_PER_TRADE_PCT,
    MAX_LEVERAGE,
)


class OrderExecutionEngine:
    def __init__(self):
        self.api_key = BINANCE_API_KEY
        self.api_secret = BINANCE_API_SECRET
        self.has_credentials = bool(self.api_key and self.api_secret)

    def _sign_payload(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    def calculate_position_parameters(self, entry_price: float, sl_price: float):
        risk_usd = EQUITY_USD * RISK_PER_TRADE_PCT
        stop_dist = max(abs(entry_price - sl_price), entry_price * 0.001)
        size_xau = risk_usd / stop_dist
        max_size = (EQUITY_USD * MAX_LEVERAGE) / entry_price
        final_size = min(size_xau, max_size)
        return round(final_size, 4), stop_dist

    async def execute_bracket(self, side: str, qty: float, sl: float, tp1: float, tp2: float):
        if not self.has_credentials:
            return {"status": "SIMULATED_SUCCESS", "side": side, "qty": qty, "sl": sl, "tp1": tp1, "tp2": tp2}

        async with aiohttp.ClientSession() as session:
            url = f"{REST_BASE}/fapi/v1/order"
            headers = {"X-MBX-APIKEY": self.api_key}
            exit_side = "SELL" if side == "BUY" else "BUY"

            # 1. Market Entry
            entry_params = self._sign_payload({"symbol": SYMBOL, "side": side, "type": "MARKET", "quantity": qty})
            async with session.post(url, data=entry_params, headers=headers) as resp:
                entry_res = await resp.json()

            # 2. Stop Loss
            sl_params = self._sign_payload({
                "symbol": SYMBOL, "side": exit_side, "type": "STOP_MARKET",
                "stopPrice": round(sl, 2), "closePosition": "true", "workingType": "MARK_PRICE"
            })
            async with session.post(url, data=sl_params, headers=headers):
                pass

            # 3. Take Profit 1 (50%)
            tp1_qty = round(qty * 0.5, 4)
            tp1_params = self._sign_payload({
                "symbol": SYMBOL, "side": exit_side, "type": "TAKE_PROFIT_MARKET",
                "stopPrice": round(tp1, 2), "quantity": tp1_qty, "reduceOnly": "true"
            })
            async with session.post(url, data=tp1_params, headers=headers):
                pass

            return entry_res


trade_executor = OrderExecutionEngine()
