"""
btquantr/engine/strategy_store.py — StrategyStore Redis-backed.

Almacena estrategias evaluadas indexadas por símbolo + régimen.

Redis keys:
  engine:store:{symbol}:{regime}  → JSON de la estrategia top
  engine:store:registry           → JSON list de {name, symbol, regime, fitness, timestamp}

Si Redis no está disponible (o r=None), opera en modo in-memory transparente.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Importación diferida de redis
try:
    import redis as _redis_module
except ImportError:
    _redis_module = None  # type: ignore[assignment]

# Exponer para que los tests puedan parchear
redis = _redis_module


class StrategyStore:
    """Almacena estrategias evaluadas en Redis, indexadas por símbolo + régimen.

    Redis keys:
      engine:store:{symbol}:{regime}  → JSON de la estrategia top
      engine:store:registry           → JSON list de {name, symbol, regime, fitness, timestamp}

    Modo in-memory: se activa automáticamente si Redis no está disponible o r=None.
    """

    def __init__(self, r=None) -> None:
        """
        Args:
            r: cliente Redis ya construido. Si None, intenta conectar.
               Si falla, activa modo in-memory.
        """
        self._r = r
        self._memory: dict[str, str] = {}   # clave → JSON string (fallback)
        self._use_memory = False

        if r is None:
            self._r = self._connect()

    # ─────────────────────────────────────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────────────────────────────────────

    def register(self, strategy: dict, regime: str, symbol: str = "BTCUSDT", venue: str = "hyperliquid") -> bool:
        """Guarda estrategia como top para symbol+regime.

        Args:
            venue: Venue de ejecución ('hyperliquid', 'mt5', 'universal', ...).
                   'universal' aparece en todos los venues al filtrar.

        Returns:
            True si se guardó correctamente.
        """
        key = self._store_key(symbol, regime)
        payload = json.dumps(strategy)

        ok = self._set(key, payload)
        if not ok:
            return False

        # Actualizar registry
        self._update_registry(strategy, symbol, regime, venue=venue)
        return True

    def get_best(self, symbol: str, regime: str) -> dict | None:
        """Retorna la mejor estrategia para symbol+regime, o None."""
        key = self._store_key(symbol, regime)
        raw = self._get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def list_registry(self) -> list[dict]:
        """Lista todas las estrategias registradas."""
        raw = self._get("engine:store:registry")
        if raw is None:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def list_registry_by_venue(self, venue: str) -> list[dict]:
        """Lista estrategias filtradas por venue.

        'universal' aparece en todos los venues.
        Entries sin campo 'venue' (registros pre-migración) se tratan como 'hyperliquid'.
        """
        all_entries = self.list_registry()
        return [
            e for e in all_entries
            if (e.get("venue") or "hyperliquid") == venue or e.get("venue") == "universal"
        ]

    def clear(self, symbol: str | None = None) -> None:
        """Elimina entries. Si symbol=None, elimina todo."""
        if self._use_memory:
            if symbol is None:
                self._memory.clear()
            else:
                prefix = f"engine:store:{symbol}:"
                keys_to_del = [k for k in self._memory if k.startswith(prefix)]
                for k in keys_to_del:
                    del self._memory[k]
                # Limpiar del registry también
                registry = self.list_registry()
                registry = [e for e in registry if e.get("symbol") != symbol]
                self._memory["engine:store:registry"] = json.dumps(registry)
        else:
            try:
                if symbol is None:
                    # Eliminar todas las claves engine:store:*
                    cursor = 0
                    while True:
                        cursor, keys = self._r.scan(cursor, match="engine:store:*", count=100)
                        if keys:
                            self._r.delete(*keys)
                        if cursor == 0:
                            break
                else:
                    # Eliminar claves del símbolo
                    cursor = 0
                    while True:
                        cursor, keys = self._r.scan(cursor, match=f"engine:store:{symbol}:*", count=100)
                        if keys:
                            self._r.delete(*keys)
                        if cursor == 0:
                            break
                    # Limpiar del registry
                    registry = self.list_registry()
                    registry = [e for e in registry if e.get("symbol") != symbol]
                    self._set("engine:store:registry", json.dumps(registry))
            except Exception as exc:
                logger.debug("Redis clear error: %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _connect(self):
        """Intenta conectar a Redis. Si falla, activa modo in-memory."""
        if redis is None:
            self._use_memory = True
            return None
        try:
            client = redis.Redis(host="localhost", port=6379, db=0, socket_connect_timeout=1)
            client.ping()
            return client
        except Exception as exc:
            logger.debug("Redis no disponible → modo in-memory: %s", exc)
            self._use_memory = True
            return None

    def _store_key(self, symbol: str, regime: str) -> str:
        return f"engine:store:{symbol}:{regime}"

    def _set(self, key: str, value: str) -> bool:
        if self._use_memory or self._r is None:
            self._memory[key] = value
            return True
        try:
            self._r.set(key, value)
            return True
        except Exception as exc:
            logger.debug("Redis set error: %s", exc)
            # Fallback a memory
            self._memory[key] = value
            return True

    def _get(self, key: str) -> str | None:
        if self._use_memory or self._r is None:
            return self._memory.get(key)
        try:
            raw = self._r.get(key)
            return raw.decode() if isinstance(raw, bytes) else raw
        except Exception as exc:
            logger.debug("Redis get error: %s", exc)
            return self._memory.get(key)

    def _update_registry(self, strategy: dict, symbol: str, regime: str, venue: str = "hyperliquid") -> None:
        """Añade o actualiza la entrada del registry."""
        registry = self.list_registry()
        entry = {
            "name": strategy.get("name", "unknown"),
            "symbol": symbol,
            "regime": regime,
            "fitness": strategy.get("fitness", 0.0),
            "timestamp": time.time(),
            "venue": venue,
        }
        # Reemplazar si ya existe la misma combinación name+symbol+regime
        registry = [
            e for e in registry
            if not (e.get("name") == entry["name"] and e.get("symbol") == symbol and e.get("regime") == regime)
        ]
        registry.append(entry)
        self._set("engine:store:registry", json.dumps(registry))
