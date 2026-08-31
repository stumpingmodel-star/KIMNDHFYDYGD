import os


# Binance USDⓈ-M Futures Endpoints
REST_BASE = "https://fapi.binance.com"
WS_BASE = "wss://fstream.binance.com/ws"
SYMBOL = "XAUUSDT"
INTERVAL = "15m"  # 15-minute scalp timeframe


# API Credentials (Optional: Leave empty for live telemetry-only / simulated mode)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
TESTNET = False


if TESTNET:
    REST_BASE = "https://testnet.binancefuture.com"
    WS_BASE = "wss://stream.binancefuture.com/ws"


# Risk & Strategy Constraints
EQUITY_USD = 10_000.0
RISK_PER_TRADE_PCT = 0.01  # 1% equity risk
MAX_LEVERAGE = 10
CASCADE_THRESHOLD_USD = 1_000_000  # $1M liquidations in 10s to arm
VELOCITY_THRESHOLD_USD_S = 100_000  # $100k/sec liquidation burst


# Display / Precision
PRICE_DECIMALS = 2
QTY_DECIMALS = 4
