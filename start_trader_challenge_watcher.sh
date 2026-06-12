#!/bin/bash
# Persistent 60-day CryptoTrader challenge watcher
cd /home/pi/Desktop/test/create/crypto_trader
export $(grep -v '^#' ../../.env | xargs)
export CHALLENGE_DAYS=60
nohup /home/pi/Desktop/test/.venv/bin/python trader.py --watch-7d-challenge >> /home/pi/Desktop/test/logs/trader_challenge_watcher.log 2>&1 &
