"""btquantr/data/sources/orderflow.py — Order Flow Imbalance via HyperLiquid WebSocket.

Suscribe al feed de trades en tiempo real de HyperLiquid y acumula buy/sell volume
en ventanas deslizantes de 5m, 15m, 1h y 4h. Publica imbalance_ratio en Redis.

Redis key: orderflow:{symbol}:imbalance → {5m, 15m, 1h, 4h, ts, symbol}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import websockets

log = logging.getLogger("OrderFlowSource")

_WS_URI = "wss://api.hyperliquid.xyz/ws"


class OrderFlowWindow:
    """Ventana de tiempo para acumular buy/sell volume."""

    def __init__(self, window_s: int):
        self.window_s = window_s          # segundos
        self.buy_volume: float = 0.0
        self.sell_volume: float = 0.0
        self._trades: list = []           # [(ts_ms, side, sz)]

    def add_trade(self, ts_ms: int, side: str, sz: float) -> None:
        """Añade trade. side: 'B' (buy) o 'A' (ask/sell)."""
        self._trades.append((ts_ms, side, sz))
        if side == "B":
            self.buy_volume += sz
        else:
            self.sell_volume += sz

    def evict_old(self, now_ms: int) -> None:
        """Elimina trades fuera de la ventana y recalcula volúmenes."""
        cutoff_ms = now_ms - self.window_s * 1000
        kept = [(ts, side, sz) for ts, side, sz in self._trades if ts >= cutoff_ms]
        self._trades = kept
        self.buy_volume = sum(sz for _, side, sz in kept if side == "B")
        self.sell_volume = sum(sz for _, side, sz in kept if side == "A")

    def imbalance_ratio(self) -> float:
        """(buy - sell) / (buy + sell). Retorna 0.0 si total == 0."""
        total = self.buy_volume + self.sell_volume
        if total == 0.0:
            return 0.0
        return (self.buy_volume - self.sell_volume) / total


class OrderFlowTracker:
    """Acumula buy/sell volume por símbolo en ventanas de 5m/15m/1h/4h.

    Calcula imbalance_ratio = (buy - sell) / (buy + sell).

    Publica en Redis:
        orderflow:{symbol}:imbalance → {
            "5m": float, "15m": float, "1h": float, "4h": float,
            "ts": float, "symbol": str
        }
    """

    WINDOWS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}

    def __init__(self, r=None):
        self._r = r
        # self.windows[symbol][window_name] = OrderFlowWindow(...)
        self.windows: dict[str, dict[str, OrderFlowWindow]] = {}

    def _get_redis(self):
        if self._r is not None:
            return self._r
        try:
            from btquantr.redis_client import get_redis
            return get_redis()
        except Exception:
            return None

    def _ensure_symbol(self, symbol: str) -> None:
        """Inicializa ventanas para un símbolo si no existen."""
        if symbol not in self.windows:
            self.windows[symbol] = {
                name: OrderFlowWindow(secs)
                for name, secs in self.WINDOWS.items()
            }

    def process_trade(self, symbol: str, ts_ms: int, side: str, sz: float) -> None:
        """Procesa un trade y actualiza todas las ventanas del símbolo."""
        self._ensure_symbol(symbol)
        now_ms = int(time.time() * 1000)
        for window in self.windows[symbol].values():
            window.evict_old(now_ms)
            window.add_trade(ts_ms, side, sz)

    def get_imbalance(self, symbol: str) -> dict:
        """Retorna dict con imbalance_ratio para cada ventana."""
        self._ensure_symbol(symbol)
        result: dict = {
            name: self.windows[symbol][name].imbalance_ratio()
            for name in self.WINDOWS
        }
        result["ts"] = time.time()
        result["symbol"] = symbol
        return result

    def publish(self, symbol: str) -> dict:
        """Llama get_imbalance y publica en Redis. Retorna el dict."""
        data = self.get_imbalance(symbol)
        r = self._get_redis()
        if r is not None:
            try:
                r.set(f"orderflow:{symbol}:imbalance", json.dumps(data))
            except Exception as e:
                log.debug(f"Redis publish error: {e}")
        return data

    async def subscribe_trades(self, coins: list[str]) -> None:
        """Suscribe al WebSocket de HL, procesa trades indefinidamente.

        Llama process_trade y publish por cada batch de trades recibido.
        """
        async with websockets.connect(_WS_URI) as ws:
            for coin in coins:
                await ws.send(json.dumps({
                    "method": "subscribe",
                    "subscription": {"type": "trades", "coin": coin}
                }))
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    if data.get("channel") == "trades":
                        for t in data.get("data", []):
                            symbol = t["coin"] + "USDT"
                            self.process_trade(
                                symbol,
                                int(t["time"]),
                                t["side"],
                                float(t["sz"])
                            )
                            self.publish(symbol)
                except Exception as e:
                    log.debug(f"Error procesando mensaje WS: {e}")
