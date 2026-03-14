"""ConfigManager — configuración centralizada del sistema en Redis."""
from __future__ import annotations
import json, logging
from typing import Any

log = logging.getLogger("BTQUANTRConfig")

DEFAULT_CONFIG: dict[str, Any] = {
    # Portfolio
    "initial_balance": 10_000.0,
    "commission_pct": 0.04,          # 0.04% por operación (HyperLiquid taker)
    "slippage_bps": 2,               # 2 basis points
    # Position sizing
    "sizing_kelly_fraction": 0.5,    # Half-Kelly
    "max_open_positions": 3,
    # Circuit breakers
    "circuit_breaker_daily": 5.0,    # % DD diario máximo
    # Sizing por régimen
    "regime_bull_max_size": 25.0,    # % del balance
    "regime_bull_max_risk": 2.0,     # % por trade
    "regime_bear_max_size": 10.0,
    "regime_bear_max_risk": 1.0,
    "regime_sideways_max_size": 15.0,
    "regime_sideways_max_risk": 1.5,
    # BacktestEngineer (Fase 2.5C)
    "backtest_engineer_trigger_trades": 25,  # auto-trigger cada N trades cerrados
    "backtest_engineer_min_trades":     10,  # mínimo de trades para poder analizar
    # Circuit breakers
    "cb_daily_loss_pct": 3.0,      # % pérdida diaria máxima
    "cb_weekly_loss_pct": 7.0,     # % pérdida semanal máxima
    "cb_max_drawdown_pct": 15.0,   # % drawdown total máximo (reset manual)
    "cb_max_positions": 5,         # posiciones abiertas máximas
    # Trading mode (Fase ASE v2 — Tarea 9)
    "trading_mode": "autonomous",  # "autonomous" | "claude" | "hybrid"
    # Storage backend para StrategyStore
    "storage_backend": "sqlite",   # "sqlite" | "redis"
}

REDIS_KEY = "system:config"


class ConfigManager:
    """Gestiona la configuración del sistema en Redis con fallback a DEFAULT_CONFIG."""

    def __init__(self, r):
        self.r = r

    def get(self, key: str, default: Any = None) -> Any:
        """Devuelve valor de config. Orden: Redis → DEFAULT_CONFIG → default."""
        raw = self.r.get(REDIS_KEY)
        stored = json.loads(raw) if raw else {}
        if key in stored:
            return stored[key]
        if key in DEFAULT_CONFIG:
            return DEFAULT_CONFIG[key]
        return default

    def set(self, key: str, value: Any) -> None:
        """Persiste un valor en Redis."""
        # TODO(concurrency): operación read-modify-write no atómica.
        # Con múltiples procesos concurrentes (CLI + Orchestrator) puede haber
        # race condition. Migrar a WATCH+pipeline Redis cuando se añada acceso concurrente.
        raw = self.r.get(REDIS_KEY)
        stored = json.loads(raw) if raw else {}
        stored[key] = value
        self.r.set(REDIS_KEY, json.dumps(stored))
        log.info(f"Config set: {key} = {value}")

    def get_all(self) -> dict:
        """Devuelve configuración completa: defaults + overrides de Redis."""
        raw = self.r.get(REDIS_KEY)
        stored = json.loads(raw) if raw else {}
        return {**DEFAULT_CONFIG, **stored}

    def reset_to_defaults(self) -> None:
        """Elimina overrides de Redis — vuelve a DEFAULT_CONFIG."""
        self.r.delete(REDIS_KEY)
        log.info("Config reseteada a defaults")
