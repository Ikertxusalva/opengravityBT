"""Datos de Binance Futures REST API (sin clave)."""
from __future__ import annotations
import httpx
from typing import Optional, List, Dict

BASE_F = "https://fapi.binance.com"


class BinanceSource:
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def get_price(self, symbol: str) -> Optional[float]:
        try:
            r = httpx.get(f"{BASE_F}/fapi/v1/ticker/price",
                          params={"symbol": symbol}, timeout=self.timeout)
            r.raise_for_status()
            return float(r.json()["price"])
        except Exception:
            return None

    def get_funding_rate(self, symbol: str, limit: int = 3) -> List[Dict]:
        try:
            r = httpx.get(f"{BASE_F}/fapi/v1/fundingRate",
                          params={"symbol": symbol, "limit": limit}, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            return []

    def get_open_interest(self, symbol: str) -> Optional[Dict]:
        try:
            r = httpx.get(f"{BASE_F}/fapi/v1/openInterest",
                          params={"symbol": symbol}, timeout=self.timeout)
            r.raise_for_status()
            d = r.json()
            return {"openInterest": float(d["openInterest"]), "symbol": symbol}
        except Exception:
            return None

    def get_long_short_ratio(self, symbol: str, period: str = "1h", limit: int = 3) -> List[Dict]:
        try:
            r = httpx.get(f"{BASE_F}/futures/data/globalLongShortAccountRatio",
                          params={"symbol": symbol, "period": period, "limit": limit},
                          timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            return []

    def get_open_interest_history(self, symbol: str, period: str = "1h", limit: int = 500) -> List[Dict]:
        try:
            r = httpx.get(f"{BASE_F}/futures/data/openInterestHist",
                          params={"symbol": symbol, "period": period, "limit": limit},
                          timeout=self.timeout)
            r.raise_for_status()
            return [{"timestamp": int(d["timestamp"]), "openInterest": float(d["sumOpenInterest"])}
                    for d in r.json()]
        except Exception:
            return []

    def get_long_short_ratio_history(self, symbol: str, period: str = "1h", limit: int = 500) -> List[Dict]:
        try:
            r = httpx.get(f"{BASE_F}/futures/data/globalLongShortAccountRatio",
                          params={"symbol": symbol, "period": period, "limit": limit},
                          timeout=self.timeout)
            r.raise_for_status()
            return [{"timestamp": int(d["timestamp"]), "longShortRatio": float(d["longShortRatio"])}
                    for d in r.json()]
        except Exception:
            return []

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> List[List]:
        try:
            r = httpx.get(f"{BASE_F}/fapi/v1/klines",
                          params={"symbol": symbol, "interval": interval, "limit": limit},
                          timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            return []
