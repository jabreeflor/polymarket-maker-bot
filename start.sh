#!/bin/bash
cd "$(dirname "$0")"
nohup python3 bot.py >> bot.log 2>&1 &
echo $! > bot.pid
echo "Bot started (PID $(cat bot.pid)). Logs: bot.log"
