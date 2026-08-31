import numpy as np
from core.indicators import QuantitativeEngine
from core.market_state import market_state


class ScalpSignalEngine:
    """
    15-minute XAU/USDT scalp signal generator.
    Returns ENTRY, IDEAL ENTRY, STOP LOSS and TARGET PRICE for LONG/SHORT setups.
    """

    def __init__(self):
        self.last_signal = None

    def _swing_window(self, klines, lookback=8):
        """Return recent swing low/high from the last N 15m candles."""
        if len(klines) < lookback:
            lookback = len(klines)
        if lookback < 2:
            return 0.0, 0.0
        window = klines[-lookback:]
        lows = [k[3] for k in window]
        highs = [k[2] for k in window]
        return min(lows), max(highs)

    def generate_signal(self) -> dict:
        klines = list(market_state.klines_15m)
        if len(klines) < 30:
            return {
                "signal": "WAIT",
                "side": None,
                "entry": 0.0,
                "ideal_entry": 0.0,
                "stop_loss": 0.0,
                "target": 0.0,
                "rr_ratio": 0.0,
                "reason": "Insufficient 15m history"
            }

        closes = np.array([k[4] for k in klines])
        highs = np.array([k[2] for k in klines])
        lows = np.array([k[3] for k in klines])

        ema_9 = QuantitativeEngine.calculate_ema(closes, 9)
        ema_21 = QuantitativeEngine.calculate_ema(closes, 21)
        vwap = QuantitativeEngine.calculate_vwap(klines)
        atr = QuantitativeEngine.calculate_atr(closes, highs, lows, period=14)
        rsi = QuantitativeEngine.calculate_rsi(closes, period=14)

        swing_low, swing_high = self._swing_window(klines, lookback=8)
        price = market_state.last_price or closes[-1]

        # Trend bias
        bullish_trend = ema_9 > ema_21
        bearish_trend = ema_9 < ema_21

        # CVD micro-bias
        cvd_bullish = market_state.recent_cvd_5s > 0.1
        cvd_bearish = market_state.recent_cvd_5s < -0.1

        signal = "WAIT"
        side = None
        entry = price
        ideal_entry = price
        stop_loss = 0.0
        target = 0.0
        reason = "No clear 15m setup"

        sl_buffer = max(atr * 1.2, price * 0.0015)
        tp_distance = max(atr * 2.0, price * 0.0025)

        if bullish_trend and rsi > 40:
            # Long setup: ideal entry is pullback to EMA9 or VWAP, whichever is lower and closer
            ideal_pullback = max(min(ema_9, vwap), swing_low)
            ideal_entry = ideal_pullback
            entry = price
            stop_loss = min(swing_low, ideal_entry - sl_buffer)
            target = ideal_entry + tp_distance
            side = "LONG"
            signal = "LONG"
            reason = "15m bullish trend, pullback buy"
            if price > ema_9 and cvd_bullish:
                reason += ", momentum confirmed"
            elif price > ema_9:
                signal = "WAIT"
                reason = "Price extended above EMA9, wait for pullback"

        elif bearish_trend and rsi < 60:
            # Short setup: ideal entry is rally to EMA9 or VWAP, whichever is higher and closer
            ideal_pullback = min(max(ema_9, vwap), swing_high)
            ideal_entry = ideal_pullback
            entry = price
            stop_loss = max(swing_high, ideal_entry + sl_buffer)
            target = ideal_entry - tp_distance
            side = "SHORT"
            signal = "SHORT"
            reason = "15m bearish trend, rally sell"
            if price < ema_9 and cvd_bearish:
                reason += ", momentum confirmed"
            elif price < ema_9:
                signal = "WAIT"
                reason = "Price extended below EMA9, wait for rally"

        # Risk / reward (computed from ideal entry, the planned trade)
        risk = abs(ideal_entry - stop_loss)
        reward = abs(target - ideal_entry)
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

        result = {
            "signal": signal,
            "side": side,
            "entry": round(entry, 2),
            "ideal_entry": round(ideal_entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target": round(target, 2),
            "rr_ratio": rr_ratio,
            "reason": reason,
            "indicators": {
                "ema_9": round(ema_9, 2),
                "ema_21": round(ema_21, 2),
                "vwap": round(vwap, 2),
                "atr": round(atr, 2),
                "rsi": round(rsi, 1)
            }
        }
        self.last_signal = result
        return result


scalp_engine = ScalpSignalEngine()
