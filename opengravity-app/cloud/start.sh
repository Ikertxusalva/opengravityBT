#!/bin/bash
# Start both the API server and data collector daemon
# Railway runs this via: CMD ["sh", "start.sh"]

# Start collector in background
python -m data_collector.collector &
COLLECTOR_PID=$!

# Start API server in foreground
uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}

# If server dies, kill collector too
kill $COLLECTOR_PID 2>/dev/null
