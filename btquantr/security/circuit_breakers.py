"""Circuit Breakers — para órdenes cuando se superan límites de pérdida.

Breakers:
  - DailyLossLimit:    pérdida diaria > threshold → bloqueado hasta mañana UTC
  - WeeklyLossLimit:   pérdida semanal > threshold → bloqueado hasta lunes UTC
  - MaxDrawdownLimit:  drawdown total > threshold → bloqueado (reset manual)
  - MaxPositions:      posiciones abiertas >= max → bloquear nuevas órdenes

Integración:
  CircuitBreakerManager.check_all(portfolio, n_open_positions) → CheckResult
  CheckResult: {"allowed": bool, "tripped_by": list[str], "details": dict}

Redis keys (con TTL automático):
  circuit:daily_loss:tripped     TTL hasta medianoche UTC
  circuit:weekly_loss:tripped    TTL hasta lunes 00:00 UTC
  circuit:max_drawdown:tripped   sin TTL (reset manual)

Config keys en ConfigManager:
  cb_daily_loss_pct     default 3.0
  cb_weekly_loss_pct    default 7.0
  cb_max_drawdown_pct   default 15.0
  cb_max_positions      default 5
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger("BTQUANTRCircuitBreakers")


def _seconds_until_midnight_utc() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((tomorrow - now).total_seconds()))


def _seconds_until_next_monday_utc() -> int:
    now = datetime.now(timezone.utc)
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = (now + timedelta(days=days_until_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((next_monday - now).total_seconds()))


class DailyLossLimit:
    """Bloquea órdenes si la pérdida diaria supera el threshold."""

    name = "DailyLossLimit"
    REDIS_KEY = "circuit:daily_loss:tripped"

    def __init__(self, threshold_pct: float = 3.0):
        self.threshold_pct = threshold_pct

    def is_tripped(self, portfolio: dict, r=None) -> bool:
        # Si Redis dice que está tripped (TTL no expiró) → sigue tripped
        if r is not None and r.get(self.REDIS_KEY):
            return True
        current = float(portfolio.get("daily_loss_pct", 0.0))
        tripped = current >= self.threshold_pct
        if tripped and r is not None:
            ttl = _seconds_until_midnight_utc()
            r.set(self.REDIS_KEY, "1", ex=ttl)
        return tripped

    def status(self, portfolio: dict, r=None) -> dict:
        current = float(portfolio.get("daily_loss_pct", 0.0))
        return {
            "name": self.name,
            "tripped": self.is_tripped(portfolio, r),
            "threshold": self.threshold_pct,
            "current_value": current,
        }


class WeeklyLossLimit:
    """Bloquea órdenes si la pérdida semanal supera el threshold."""

    name = "WeeklyLossLimit"
    REDIS_KEY = "circuit:weekly_loss:tripped"

    def __init__(self, threshold_pct: float = 7.0):
        self.threshold_pct = threshold_pct

    def is_tripped(self, portfolio: dict, r=None) -> bool:
        if r is not None and r.get(self.REDIS_KEY):
            return True
        current = float(portfolio.get("weekly_loss_pct", 0.0))
        tripped = current >= self.threshold_pct
        if tripped and r is not None:
            ttl = _seconds_until_next_monday_utc()
            r.set(self.REDIS_KEY, "1", ex=ttl)
        return tripped

    def status(self, portfolio: dict, r=None) -> dict:
        current = float(portfolio.get("weekly_loss_pct", 0.0))
        return {
            "name": self.name,
            "tripped": self.is_tripped(portfolio, r),
            "threshold": self.threshold_pct,
            "current_value": current,
        }


class MaxDrawdownLimit:
    """Bloquea órdenes si el drawdown total supera el threshold (reset manual)."""

    name = "MaxDrawdownLimit"
    REDIS_KEY = "circuit:max_drawdown:tripped"

    def __init__(self, threshold_pct: float = 15.0):
        self.threshold_pct = threshold_pct

    def is_tripped(self, portfolio: dict, r=None) -> bool:
        if r is not None and r.get(self.REDIS_KEY):
            return True
        current = float(portfolio.get("total_dd_pct", 0.0))
        tripped = current >= self.threshold_pct
        if tripped and r is not None:
            r.set(self.REDIS_KEY, "1")  # Sin TTL — reset manual requerido
        return tripped

    def status(self, portfolio: dict, r=None) -> dict:
        current = float(portfolio.get("total_dd_pct", 0.0))
        return {
            "name": self.name,
            "tripped": self.is_tripped(portfolio, r),
            "threshold": self.threshold_pct,
            "current_value": current,
        }


class MaxPositions:
    """Bloquea nuevas órdenes si el número de posiciones abiertas >= max."""

    name = "MaxPositions"

    def __init__(self, max_positions: int = 5):
        self.max_positions = max_positions

    def is_tripped(self, n_open_positions: int, r=None) -> bool:
        return n_open_positions >= self.max_positions

    def status(self, n_open_positions: int, r=None) -> dict:
        return {
            "name": self.name,
            "tripped": self.is_tripped(n_open_positions),
            "threshold": self.max_positions,
            "current_value": n_open_positions,
        }


class CircuitBreakerManager:
    """Gestiona todos los circuit breakers.

    check_all(portfolio, n_open_positions) → {"allowed": bool, "tripped_by": list, "details": dict}
    """

    def __init__(
        self,
        daily_limit: Optional[DailyLossLimit] = None,
        weekly_limit: Optional[WeeklyLossLimit] = None,
        drawdown_limit: Optional[MaxDrawdownLimit] = None,
        max_positions: Optional[MaxPositions] = None,
        r=None,
    ):
        self.daily = daily_limit or DailyLossLimit()
        self.weekly = weekly_limit or WeeklyLossLimit()
        self.drawdown = drawdown_limit or MaxDrawdownLimit()
        self.positions = max_positions or MaxPositions()
        self._r = r

    def check_all(self, portfolio: dict, n_open_positions: int = 0) -> dict:
        """Verifica todos los breakers y retorna resultado consolidado."""
        tripped_by = []
        details = {}

        for breaker in [self.daily, self.weekly, self.drawdown]:
            st = breaker.status(portfolio, self._r)
            details[breaker.name] = st
            if st["tripped"]:
                tripped_by.append(breaker.name)
                log.warning(
                    "Circuit breaker TRIPPED: %s (current=%.2f%% >= threshold=%.2f%%)",
                    breaker.name,
                    st["current_value"],
                    st["threshold"],
                )

        pos_st = self.positions.status(n_open_positions, self._r)
        details[self.positions.name] = pos_st
        if pos_st["tripped"]:
            tripped_by.append(self.positions.name)
            log.warning(
                "Circuit breaker TRIPPED: MaxPositions (open=%d >= max=%d)",
                n_open_positions,
                self.positions.max_positions,
            )

        return {
            "allowed": len(tripped_by) == 0,
            "tripped_by": tripped_by,
            "details": details,
        }

    def status_all(self, portfolio: dict, n_open_positions: int = 0) -> list[dict]:
        """Retorna lista de status de todos los breakers."""
        result = []
        for breaker in [self.daily, self.weekly, self.drawdown]:
            result.append(breaker.status(portfolio, self._r))
        result.append(self.positions.status(n_open_positions, self._r))
        return result
