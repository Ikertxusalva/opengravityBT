#!/bin/bash
# Start both the API server and data collector daemon
# Railway runs this via: CMD ["sh", "start.sh"]

echo "[START] Launching data collector daemon..."
python -m data_collector.collector 2>&1 | while read line; do echo "[COLLECTOR] $line"; done &
COLLECTOR_PID=$!
echo "[START] Collector PID: $COLLECTOR_PID"

echo "[START] Launching API server..."
uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}

# If server dies, kill collector too
kill $COLLECTOR_PID 2>/dev/null
