#!/bin/bash
cd "$(dirname "$0")"
if [ -f bot.pid ]; then
    kill $(cat bot.pid) 2>/dev/null && echo "Bot stopped." || echo "Bot not running."
    rm -f bot.pid
else
    echo "No PID file found."
fi
