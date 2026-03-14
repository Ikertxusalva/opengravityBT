"""Publica régimen en Redis y notifica cambios vía PUB/SUB."""
from __future__ import annotations
import json, logging, time
from typing import Dict
import redis as redis_lib

log = logging.getLogger("RegimePublisher")


class RegimePublisher:
    def __init__(self, r: redis_lib.Redis):
        self.r = r
        self._last: Dict[str, int] = {}

    def publish(self, symbol: str, regime: Dict) -> None:
        self.r.set(f"regime:{symbol}", json.dumps(regime))
        self.r.set(f"regime:{symbol}:timestamp", str(regime["timestamp"]))
        prev = self._last.get(symbol)
        curr = regime["state"]
        if prev is not None and prev != curr:
            change = {"symbol": symbol, "from_state": prev, "to_state": curr,
                      "to_name": regime["state_name"], "confidence": regime["confidence"],
                      "timestamp": regime["timestamp"]}
            self.r.publish("regime_changes", json.dumps(change))
            log.warning(f"CAMBIO RÉGIMEN {symbol}: {prev}→{curr} ({regime['state_name']})")
        self._last[symbol] = curr
        self.r.set("health:regime_service", json.dumps(
            {"status": "ok", "last_prediction": time.time(), "symbols": list(self._last.keys())}))
