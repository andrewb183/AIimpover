#!/bin/bash
# Start CryptoTrader monitor at boot
cd /home/pi/Desktop/test/create/crypto_trader
nohup /home/pi/Desktop/test/.venv/bin/python trader.py --monitor >> /home/pi/Desktop/test/logs/trader_monitor.log 2>&1 &
