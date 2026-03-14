"""
btquantr/engine/strategy_store_factory.py — Factory para StrategyStore.

Selecciona SQLiteStrategyStore o StrategyStore (Redis) según backend.
"""
from __future__ import annotations


def get_strategy_store(backend: str = "sqlite", db_path: str | None = None):
    """Retorna la implementación de StrategyStore según el backend.

    Args:
        backend: "sqlite" (default) | "redis"
        db_path: Ruta al fichero SQLite (solo si backend="sqlite").

    Returns:
        SQLiteStrategyStore | StrategyStore

    Raises:
        ValueError: Si el backend no es válido.
    """
    if backend == "sqlite":
        from btquantr.engine.strategy_store_sqlite import SQLiteStrategyStore
        return SQLiteStrategyStore(db_path=db_path)
    elif backend == "redis":
        from btquantr.engine.strategy_store import StrategyStore
        return StrategyStore()
    else:
        raise ValueError(f"backend inválido: '{backend}'. Usa 'sqlite' o 'redis'.")
