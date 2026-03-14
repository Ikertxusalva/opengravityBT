"""
btquantr/engine/strategy_store_sqlite.py — SQLiteStrategyStore.

Almacena estrategias evaluadas en SQLite, misma interfaz que StrategyStore Redis.

Tabla: strategies(id, symbol, regime, name, code, params_json, fitness, created_at)
DB por defecto: data/strategies.db
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Path por defecto: data/strategies.db relativo a la raíz del proyecto
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "data" / "strategies.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS strategies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol     TEXT    NOT NULL,
    regime     TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    code       TEXT    NOT NULL DEFAULT '',
    params_json TEXT   NOT NULL DEFAULT '{}',
    fitness    REAL    NOT NULL DEFAULT 0.0,
    created_at REAL    NOT NULL,
    venue      TEXT    NOT NULL DEFAULT 'hyperliquid'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_strategies_key
    ON strategies (symbol, regime, name);
"""

_MIGRATE_ADD_VENUE = """
ALTER TABLE strategies ADD COLUMN venue TEXT NOT NULL DEFAULT 'hyperliquid';
"""


class SQLiteStrategyStore:
    """Almacena estrategias en SQLite. Misma interfaz que StrategyStore.

    Args:
        db_path: Ruta al fichero SQLite. Default: data/strategies.db
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or _DEFAULT_DB_PATH
        # Crear directorio si no existe
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ─────────────────────────────────────────────────────────────────────────
    # API pública (misma interfaz que StrategyStore)
    # ─────────────────────────────────────────────────────────────────────────

    def register(self, strategy: dict, regime: str, symbol: str = "BTCUSDT",
                 venue: str = "hyperliquid") -> bool:
        """Guarda/actualiza estrategia para symbol+regime.

        Si ya existe una entrada con el mismo (symbol, regime, name), la actualiza.
        Returns True si se guardó correctamente.
        """
        name = strategy.get("name", "unknown")
        code = strategy.get("code", "")
        params = strategy.get("params", {})
        fitness = float(strategy.get("fitness", 0.0))
        created_at = time.time()
        venue = strategy.get("venue", venue)

        # Serializar todo el dict (excepto _returns que puede ser muy grande)
        full_payload = {k: v for k, v in strategy.items() if k != "_returns"}
        full_payload["venue"] = venue

        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO strategies (symbol, regime, name, code, params_json, fitness, created_at, venue)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, regime, name) DO UPDATE SET
                        code       = excluded.code,
                        params_json = excluded.params_json,
                        fitness    = excluded.fitness,
                        created_at = excluded.created_at,
                        venue      = excluded.venue
                    """,
                    (symbol, regime, name, code, json.dumps(full_payload), fitness, created_at, venue),
                )
            return True
        except Exception as exc:
            logger.error("SQLiteStrategyStore.register error: %s", exc)
            return False

    def get_best(self, symbol: str, regime: str) -> dict | None:
        """Retorna la estrategia con mayor fitness para symbol+regime, o None."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT params_json FROM strategies "
                    "WHERE symbol=? AND regime=? "
                    "ORDER BY fitness DESC LIMIT 1",
                    (symbol, regime),
                ).fetchone()
            if row is None:
                return None
            return json.loads(row[0])
        except Exception as exc:
            logger.error("SQLiteStrategyStore.get_best error: %s", exc)
            return None

    def list_registry(self) -> list[dict]:
        """Lista todas las entradas del registry con metadatos."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT name, symbol, regime, fitness, created_at, venue FROM strategies"
                ).fetchall()
            return [
                {
                    "name": r[0],
                    "symbol": r[1],
                    "regime": r[2],
                    "fitness": r[3],
                    "timestamp": r[4],
                    "venue": r[5],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.error("SQLiteStrategyStore.list_registry error: %s", exc)
            return []

    def list_registry_by_venue(self, venue: str) -> list[dict]:
        """Lista entradas del registry filtradas por venue."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT name, symbol, regime, fitness, created_at, venue FROM strategies "
                    "WHERE venue=? OR venue='universal'",
                    (venue,),
                ).fetchall()
            return [
                {
                    "name": r[0],
                    "symbol": r[1],
                    "regime": r[2],
                    "fitness": r[3],
                    "timestamp": r[4],
                    "venue": r[5],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.error("SQLiteStrategyStore.list_registry_by_venue error: %s", exc)
            return []

    def clear(self, symbol: str | None = None) -> None:
        """Elimina entradas. Si symbol=None, elimina todo."""
        try:
            with self._connect() as conn:
                if symbol is None:
                    conn.execute("DELETE FROM strategies")
                else:
                    conn.execute("DELETE FROM strategies WHERE symbol=?", (symbol,))
        except Exception as exc:
            logger.error("SQLiteStrategyStore.clear error: %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(_CREATE_TABLE)
                # Migración: añadir columna venue si no existe (bases de datos antiguas)
                cols = {row[1] for row in conn.execute("PRAGMA table_info(strategies)")}
                if "venue" not in cols:
                    conn.execute("ALTER TABLE strategies ADD COLUMN venue TEXT NOT NULL DEFAULT 'hyperliquid'")
        except Exception as exc:
            logger.error("SQLiteStrategyStore._init_db error: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Migración desde Redis StrategyStore
# ─────────────────────────────────────────────────────────────────────────────

def migrate_from_redis(redis_store, sqlite_store: SQLiteStrategyStore) -> int:
    """Migra estrategias de un StrategyStore (Redis/memory) a SQLiteStrategyStore.

    Args:
        redis_store: instancia de StrategyStore (Redis o in-memory).
        sqlite_store: instancia de SQLiteStrategyStore destino.

    Returns:
        Número de estrategias migradas.
    """
    registry = redis_store.list_registry()
    count = 0
    for entry in registry:
        symbol = entry.get("symbol", "BTCUSDT")
        regime = entry.get("regime", "BULL")
        # Intentar recuperar el dict completo
        full = redis_store.get_best(symbol, regime)
        if full is None:
            # Usar la entrada del registry como fallback mínimo
            full = {
                "name": entry.get("name", "unknown"),
                "fitness": entry.get("fitness", 0.0),
            }
        ok = sqlite_store.register(full, regime=regime, symbol=symbol)
        if ok:
            count += 1
    return count
