def _cumulative_loss():
    """Calculate the cumulative realized loss from trades."""
    trades = _load_json(TRADES_FILE, [])
    return abs(sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) < 0))
#!/usr/bin/env python3
import os
import sys
try:
    from dotenv import load_dotenv, find_dotenv
    dotenv_path = find_dotenv()
    if dotenv_path:
        load_dotenv(dotenv_path, override=True)
    else:
        print('[.env] No .env file found, environment variables may be missing.')
except ImportError:
    print('[.env] python-dotenv not installed, environment variables may be missing.')
import json
import time
import argparse
import random
from datetime import datetime, timezone

AIRDROP_TRIGGER_POLL_MIN = 120
AIRDROP_TRIGGER_THRESHOLD_USD = 35.0
AIRDROP_TRIGGER_MAX_USD = 5000.0
KRAKEN_TRANSFER_REQUEST_USD = 25.0
AIRDROP_TRIGGER_COOLDOWN_MIN = 360
MAX_OPEN_POSITIONS = 1000
MAX_SLIPPAGE_PCT = 0.04
MIN_24H_VOLUME_USD = 100_000
ALLOWED_EXCHANGES = ["coinbase", "kraken"]
STATE_DIR = os.path.dirname(__file__)
POSITIONS_FILE = os.path.join(STATE_DIR, "positions.json")
TRADES_FILE = os.path.join(STATE_DIR, "trades.json")
QUEUE_FILE = os.path.join(STATE_DIR, "trading_queue.json")
DASHBOARD_FILE = os.path.join(STATE_DIR, "trading_dashboard.md")
MAX_LOSS_USD = 3.0

def _write_atomic(path, data):
    """Auto-generated docstring."""
    with open(path, "w") as f:
        if isinstance(data, (list, dict)):
            json.dump(data, f, indent=2)
        else:
            f.write(str(data))

def _load_json(path, default=None):
    """Auto-generated docstring."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else []

def send_email(subject, body):
    """Auto-generated docstring."""
    import smtplib
    from email.mime.text import MIMEText
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "") or os.environ.get("SMTP_PASSWORD", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)
    smtp_to = os.environ.get("EMAIL_RECIPIENT", "")
    if not smtp_to:
        # Try to read from .env manually as fallback
        try:
            with open(os.path.join(os.path.dirname(__file__), '../../.env')) as f:
                for line in f:
                    if line.strip().startswith('EMAIL_RECIPIENT='):
                        smtp_to = line.strip().split('=',1)[1]
                        break
        except Exception:
            pass
    if not smtp_to:
        print(f"[EMAIL] No recipient set. Please set EMAIL_RECIPIENT in your .env. Subject: {subject}\n{body}")
        return False
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = smtp_to
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [smtp_to], msg.as_string())
        print(f"[EMAIL] Sent to {smtp_to}: {subject}")
        return True
    except Exception as e:
        print(f"[EMAIL] Failed to send: {e}\nSubject: {subject}\n{body}")
        return False

def _is_live():
    """Auto-generated docstring."""
    return os.environ.get("DRY_RUN", "true").lower() not in ("1", "true", "yes", "on")

def _get_exchange(name):
    """Auto-generated docstring."""
    try:
        import ccxt
        if name.lower() == "kraken":
            key = os.environ.get("KRAKEN_API_KEY", "").strip()
            secret = os.environ.get("KRAKEN_SECRET", "").strip()
            if key and secret:
                return ccxt.kraken({"apiKey": key, "secret": secret, "enableRateLimit": True})
        if name.lower() == "coinbase":
            key = os.environ.get("COINBASE_API_KEY", "").strip()
            secret = os.environ.get("COINBASE_SECRET", "").strip()
            if key and secret:
                # Try coinbasepro first, fallback to coinbase if not available
                try:
                    return ccxt.coinbasepro({"apiKey": key, "secret": secret, "enableRateLimit": True})
                except AttributeError:
                    print("[coinbase] ccxt.coinbasepro not available, falling back to ccxt.coinbase.")
                    return ccxt.coinbase({"apiKey": key, "secret": secret, "enableRateLimit": True})
    except Exception as e:
        print(f"[_get_exchange] Error loading ccxt exchange {name}: {e}")
    class DummyEx:
        """Auto-generated docstring."""
        def fetch_ohlcv(self, sym, tf, limit=60):
            """Auto-generated docstring."""
            return [[0,0,0,0,random.uniform(10,100)] for _ in range(limit)]
        def fetch_ticker(self, pair):
            """Auto-generated docstring."""
            return {"last": random.uniform(10,100), "bid": random.uniform(10,100)}
        def create_limit_buy_order(self, pair, amount, price):
            """Auto-generated docstring."""
            return {"id": f"order_{random.randint(1000,9999)}"}
        def load_markets(self):
            """Auto-generated docstring."""
            return None
    return DummyEx()

# ...existing code...
