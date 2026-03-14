"""OKX public liquidation aggregator — no API key required.

Publica en Redis: derivatives:{SYMBOL}:okx_liq
Formato: {"long_liq_usd": float, "short_liq_usd": float, "net_liq": float, "count": int}

net_liq > 0 → más shorts liquidados → presión alcista (short squeeze)
net_liq < 0 → más longs liquidados → presión bajista
"""
from __future__ import annotations

import logging
import httpx

log = logging.getLogger("OKXLiqSource")

BASE = "https://www.okx.com/api/v5/public"

# Coin (HL format) → OKX instFamily
_OKX_MAP: dict[str, str] = {
    "BTC":  "BTC-USDT",
    "ETH":  "ETH-USDT",
    "SOL":  "SOL-USDT",
    "ARB":  "ARB-USDT",
    "DOGE": "DOGE-USDT",
    "LINK": "LINK-USDT",
    "AVAX": "AVAX-USDT",
    "BNB":  "BNB-USDT",
    "XRP":  "XRP-USDT",
    "LTC":  "LTC-USDT",
}


class OKXLiqSource:
    def __init__(self, timeout: float = 10.0, _cache_manager=None):
        self.timeout = timeout
        self._cm = _cache_manager

    def _cm_or_default(self):
        if self._cm is not None:
            return self._cm
        from btquantr.data.cache_manager import CacheManager
        return CacheManager()

    def get_liq_summary(self, coin: str, limit: int = 100) -> dict | None:
        """Agrega liquidaciones recientes de OKX para un coin.

        Args:
            coin: Símbolo sin USDT (ej: "BTC", "ETH", "SOL").
            limit: Máximo de registros a pedir (1-100).

        Returns:
            {"long_liq_usd", "short_liq_usd", "net_liq", "count"} o None.
        """
        inst_family = _OKX_MAP.get(coin.upper())
        if not inst_family:
            return None

        cm = self._cm_or_default()
        cache_key = f"okx_liq_{coin.upper()}"
        cached = cm.get_json(cache_key, ttl_hours=24)
        if cached is not None:
            return cached

        try:
            r = httpx.get(
                f"{BASE}/liquidation-orders",
                params={
                    "instType":   "SWAP",
                    "instFamily": inst_family,
                    "state":      "filled",
                    "limit":      min(limit, 100),
                },
                timeout=self.timeout,
            )
            data = r.json()
            if data.get("code") != "0":
                log.warning(f"OKX API error for {coin}: {data.get('msg')}")
                return None

            long_liq = 0.0
            short_liq = 0.0
            count = 0

            for entry in data.get("data", []):
                for detail in entry.get("details", []):
                    try:
                        pos_side = detail.get("posSide", "")
                        bk_px = float(detail.get("bkPx", 0) or 0)
                        sz = float(detail.get("sz", 0) or 0)
                        usd = bk_px * sz
                        if pos_side == "long":
                            long_liq += usd
                        else:
                            short_liq += usd
                        count += 1
                    except (TypeError, ValueError):
                        continue

            result = {
                "long_liq_usd":  round(long_liq, 2),
                "short_liq_usd": round(short_liq, 2),
                "net_liq":       round(short_liq - long_liq, 2),
                "count":         count,
            }
            cm.set_json(cache_key, result, ttl_hours=24)
            return result
        except Exception as e:
            log.warning(f"OKXLiqSource.get_liq_summary({coin}) error: {e}")
            return None
