"""MultiExchangeLiqSource — WebSocket liquidation aggregator.

Conecta simultáneamente a:
- Binance Futures: wss://fstream.binance.com/ws/!forceOrder@arr
- Bybit Linear:   wss://stream.bybit.com/v5/public/linear (liquidation.<SYMBOL>)

Combina con OKXLiqSource (HTTP poll) si existe.

Redis keys:
- liq:{exchange}:{symbol}  → JSON list, últimas 100 liquidaciones
- liq:combined:{symbol}    → agregado últimas 5 min de todos los exchanges

LiqEvent normalizado:
    {
        "exchange": "binance" | "bybit" | "okx",
        "symbol":   "BTCUSDT",
        "side":     "buy" | "sell",   # buy = short squeeze, sell = long liquidated
        "size_usd": float,
        "price":    float,
        "ts":       int,              # unix ms
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Optional

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore

log = logging.getLogger("MultiExchangeLiqSource")

_BINANCE_WS = "wss://fstream.binance.com/ws/!forceOrder@arr"
_BYBIT_WS   = "wss://stream.bybit.com/v5/public/linear"

# TTL para Redis keys (1 hora)
_TTL_SECONDS = 3600
# Máx eventos por exchange+symbol almacenados en Redis
_MAX_EVENTS = 100


class MultiExchangeLiqSource:
    """Agrega liquidaciones en tiempo real de Binance + Bybit (+ OKX REST).

    Args:
        symbols:      Lista de símbolos en formato Binance/Bybit (ej. ["BTCUSDT"]).
        redis_client: Instancia Redis ya conectada (fakeredis OK para tests).
    """

    def __init__(self, symbols: list[str], redis_client=None):
        self.symbols = [s.upper() for s in symbols]
        self.redis = redis_client
        self._running = False
        # {symbol: [LiqEvent, ...]}  — buffer en memoria
        self._events: dict[str, list[dict]] = defaultdict(list)
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Inicia WebSocket connections para Binance y Bybit."""
        self._running = True
        try:
            await asyncio.gather(
                self._run_binance(),
                self._run_bybit(),
                return_exceptions=True,
            )
        finally:
            self._running = False

    async def stop(self) -> None:
        """Para todas las conexiones."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    async def _handle_binance_message(self, msg: dict) -> dict | None:
        """Parsea mensaje Binance forceOrder → LiqEvent normalizado.

        Returns:
            LiqEvent dict o None si símbolo no registrado o mensaje inválido.
        """
        try:
            order = msg.get("o", {})
            symbol = order.get("s", "")
            if symbol not in self.symbols:
                return None

            raw_side = order.get("S", "").upper()
            # Binance: SELL order = long position liquidated
            side = "sell" if raw_side == "SELL" else "buy"

            price = float(order.get("ap") or order.get("p") or 0)
            qty   = float(order.get("l") or order.get("q") or 0)
            ts    = int(order.get("T") or msg.get("E") or int(time.time() * 1000))

            return {
                "exchange": "binance",
                "symbol":   symbol,
                "side":     side,
                "size_usd": round(price * qty, 2),
                "price":    price,
                "ts":       ts,
            }
        except (TypeError, ValueError, KeyError) as exc:
            log.debug(f"_handle_binance_message error: {exc}")
            return None

    async def _handle_bybit_message(self, msg: dict) -> dict | None:
        """Parsea mensaje Bybit liquidation → LiqEvent normalizado.

        Returns:
            LiqEvent dict o None si símbolo no registrado o mensaje inválido.
        """
        try:
            data = msg.get("data", {})
            if not data:
                return None

            symbol = data.get("symbol", "")
            if symbol not in self.symbols:
                return None

            raw_side = data.get("side", "").upper()
            # Bybit: Buy order → short position liquidated (short squeeze)
            side = "buy" if raw_side == "BUY" else "sell"

            price = float(data.get("price") or 0)
            qty   = float(data.get("size") or 0)
            ts    = int(data.get("updatedTime") or msg.get("ts") or int(time.time() * 1000))

            return {
                "exchange": "bybit",
                "symbol":   symbol,
                "side":     side,
                "size_usd": round(price * qty, 2),
                "price":    price,
                "ts":       ts,
            }
        except (TypeError, ValueError, KeyError) as exc:
            log.debug(f"_handle_bybit_message error: {exc}")
            return None

    def get_summary(self, symbol: str, window_seconds: int = 300) -> dict:
        """Retorna resumen de liquidaciones dentro de la ventana temporal.

        Args:
            symbol:         Símbolo (ej. "BTCUSDT").
            window_seconds: Ventana en segundos hacia atrás desde ahora.

        Returns:
            {
                "total_volume_usd": float,
                "count": int,
                "buy_liq": float,
                "sell_liq": float,
                "exchanges": {
                    "binance": {"count": int, "volume_usd": float},
                    ...
                }
            }
        """
        symbol = symbol.upper()
        cutoff_ms = int((time.time() - window_seconds) * 1000)

        events = [
            ev for ev in self._events.get(symbol, [])
            if ev["ts"] >= cutoff_ms
        ]

        total_volume = 0.0
        buy_liq = 0.0
        sell_liq = 0.0
        exchanges: dict[str, dict] = {}

        for ev in events:
            vol = ev["size_usd"]
            total_volume += vol
            if ev["side"] == "buy":
                buy_liq += vol
            else:
                sell_liq += vol

            exch = ev["exchange"]
            if exch not in exchanges:
                exchanges[exch] = {"count": 0, "volume_usd": 0.0}
            exchanges[exch]["count"] += 1
            exchanges[exch]["volume_usd"] += vol

        return {
            "total_volume_usd": round(total_volume, 2),
            "count":            len(events),
            "buy_liq":          round(buy_liq, 2),
            "sell_liq":         round(sell_liq, 2),
            "exchanges":        exchanges,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_event(self, event: dict) -> None:
        """Almacena un LiqEvent en el buffer interno."""
        symbol = event["symbol"].upper()
        self._events[symbol].append(event)
        # Limitar buffer en memoria a 1000 por símbolo
        if len(self._events[symbol]) > 1000:
            self._events[symbol] = self._events[symbol][-1000:]

    def _publish_to_redis(self, symbol: str) -> None:
        """Publica las últimas 100 liquidaciones por exchange en Redis."""
        if self.redis is None:
            return

        symbol = symbol.upper()
        events = self._events.get(symbol, [])

        # Agrupar por exchange
        by_exchange: dict[str, list[dict]] = defaultdict(list)
        for ev in events:
            by_exchange[ev["exchange"]].append(ev)

        for exchange, evs in by_exchange.items():
            key = f"liq:{exchange}:{symbol}"
            payload = json.dumps(evs[-_MAX_EVENTS:])
            self.redis.set(key, payload, ex=_TTL_SECONDS)

    def _publish_combined(self, symbol: str, window_seconds: int = 300) -> None:
        """Publica el agregado de todos los exchanges en liq:combined:{symbol}."""
        if self.redis is None:
            return

        summary = self.get_summary(symbol, window_seconds=window_seconds)
        key = f"liq:combined:{symbol}"
        self.redis.set(key, json.dumps(summary), ex=_TTL_SECONDS)

    # ------------------------------------------------------------------
    # WebSocket loops
    # ------------------------------------------------------------------

    async def _run_binance(self) -> None:
        """Loop WebSocket Binance — reconecta si cae."""
        if websockets is None:  # pragma: no cover
            log.error("websockets no instalado")
            return

        while self._running:
            try:
                async with websockets.connect(_BINANCE_WS) as ws:
                    log.info("Binance WS conectado")
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        event = await self._handle_binance_message(msg)
                        if event:
                            self._store_event(event)
                            self._publish_to_redis(event["symbol"])
                            self._publish_combined(event["symbol"])
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                log.warning(f"Binance WS error, reconectando: {exc}")
                await asyncio.sleep(5)

    async def _run_bybit(self) -> None:
        """Loop WebSocket Bybit — reconecta si cae."""
        if websockets is None:  # pragma: no cover
            log.error("websockets no instalado")
            return

        while self._running:
            try:
                async with websockets.connect(_BYBIT_WS) as ws:
                    log.info("Bybit WS conectado")
                    # Suscribirse a liquidaciones de cada símbolo
                    sub_msg = {
                        "op": "subscribe",
                        "args": [f"liquidation.{sym}" for sym in self.symbols],
                    }
                    await ws.send(json.dumps(sub_msg))

                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        # Ignorar mensajes de control (pong, subscribe ack)
                        if msg.get("op") in ("pong", "subscribe"):
                            continue
                        event = await self._handle_bybit_message(msg)
                        if event:
                            self._store_event(event)
                            self._publish_to_redis(event["symbol"])
                            self._publish_combined(event["symbol"])
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                log.warning(f"Bybit WS error, reconectando: {exc}")
                await asyncio.sleep(5)
