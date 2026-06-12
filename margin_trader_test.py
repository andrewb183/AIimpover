# margin_trader_test.py
"""
Experimental: Margin Trading Support for Kraken (Test Only)
- Uses ccxt margin trading API
- Allows specifying leverage and margin type
- Does NOT affect live CryptoTrader code
"""

import os
import ccxt
from datetime import datetime

# Config (test values or from .env)
KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_SECRET = os.environ.get("KRAKEN_SECRET", "")
LEVERAGE = int(os.environ.get("MARGIN_LEVERAGE", "2"))  # e.g., 2x
MARGIN_TYPE = os.environ.get("MARGIN_TYPE", "cross")   # 'cross' or 'isolated'
PAIR = os.environ.get("MARGIN_PAIR", "BTC/USD")
ORDER_SIZE = float(os.environ.get("MARGIN_ORDER_SIZE", "0.001"))

# Connect to Kraken
kraken = ccxt.kraken({
    'apiKey': KRAKEN_API_KEY,
    'secret': KRAKEN_SECRET,
    'enableRateLimit': True,
})

# Fetch margin balance
try:
    margin_balance = kraken.fetch_balance({'type': 'margin'})
    print("[Margin Balance]", margin_balance)
except Exception as e:
    print("[Error] Fetching margin balance:", e)

# --- Multi-coin Kraken and Coinbase trading ---
def trade_all_pairs():
    """Auto-generated docstring."""
    print("\n[Kraken] Loading all tradable pairs...")
    try:
        kraken.load_markets()
        margin_pairs = [symbol for symbol, m in kraken.markets.items() if m.get('margin', False)]
        print(f"[Kraken] Margin pairs: {margin_pairs}")
        SIDE = os.environ.get("MARGIN_SIDE", "buy").lower()
        ORDER_TYPE = os.environ.get("MARGIN_ORDER_TYPE", "limit").lower()
        for pair in margin_pairs:
            try:
                ticker = kraken.fetch_ticker(pair)
                price = ticker['last']
                params = {'leverage': LEVERAGE}
                print(f"[Kraken] Placing margin order: {pair} {SIDE} {ORDER_TYPE} {ORDER_SIZE} @ {price}")
                order = kraken.create_order(pair, ORDER_TYPE, SIDE, ORDER_SIZE, price if ORDER_TYPE=="limit" else None, params)
                print("[Order Result]", order)
            except Exception as e:
                print(f"[Kraken][{pair}] Error: {e}")
    except Exception as e:
        print("[Kraken] Error loading markets or trading:", e)

    print("\n[Coinbase] Loading all tradable pairs...")
    try:
        coinbase = ccxt.coinbase({
            'apiKey': os.environ.get("COINBASE_API_KEY", ""),
            'secret': os.environ.get("COINBASE_SECRET", ""),
            'enableRateLimit': True,
        })
        coinbase.load_markets()
        spot_pairs = list(coinbase.markets.keys())
        print(f"[Coinbase] Spot pairs: {spot_pairs}")
    except Exception as e:
        print("[Coinbase] Error loading markets:", e)

trade_all_pairs()

# Fetch open margin positions
try:
    positions = kraken.private_post_openpositions({'docalcs': True})
    print("[Open Margin Positions]", positions)
except Exception as e:
    print("[Error] Fetching open margin positions:", e)

# Fetch margin collateral and liquidation info (if available)
try:
    account_info = kraken.private_post_tradebalance({'asset': 'ZUSD'})
    print("[Margin Account Info]", account_info)
except Exception as e:
    print("[Error] Fetching margin account info:", e)
