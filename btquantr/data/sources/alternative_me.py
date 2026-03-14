"""Fear & Greed Index de Alternative.me (sin clave)."""
import httpx
from typing import Optional, Dict


class FearGreedSource:
    URL = "https://api.alternative.me/fng/"
    _CACHE_KEY = "fear_greed"

    def __init__(self, timeout: float = 10.0, _cache_manager=None):
        self.timeout = timeout
        self._cm = _cache_manager

    def _cm_or_default(self):
        if self._cm is not None:
            return self._cm
        from btquantr.data.cache_manager import CacheManager
        return CacheManager()

    def get_latest(self) -> Optional[Dict]:
        cm = self._cm_or_default()
        cached = cm.get_json(self._CACHE_KEY, ttl_hours=24)
        if cached is not None:
            return cached
        try:
            r = httpx.get(self.URL, params={"limit": 1}, timeout=self.timeout)
            r.raise_for_status()
            d = r.json()["data"][0]
            result = {"value": int(d["value"]), "class": d["value_classification"],
                      "timestamp": int(d["timestamp"])}
            cm.set_json(self._CACHE_KEY, result, ttl_hours=24)
            return result
        except Exception:
            return None

    def get_history(self, limit: int = 365) -> list:
        cm = self._cm_or_default()
        cache_key = f"fear_greed_history_{limit}"
        cached = cm.get_json(cache_key, ttl_hours=24)
        if cached is not None:
            return cached
        try:
            r = httpx.get(self.URL, params={"limit": limit, "format": "json"},
                          timeout=self.timeout)
            r.raise_for_status()
            result = [{"value": int(d["value"]), "class": d["value_classification"],
                       "timestamp": int(d["timestamp"])}
                      for d in r.json()["data"]]
            cm.set_json(cache_key, result, ttl_hours=24)
            return result
        except Exception:
            return []
