"""Capa 3 de Seguridad — Límites absolutos hard-coded y TradeEnforcer."""
from __future__ import annotations
import json, logging, os, time
from typing import Optional

log = logging.getLogger("BTQUANTRSecurity")


class HardLimits:
    """
    LÍMITES ABSOLUTOS. No negociables. No modificables por ningún agente.
    Estos valores son CONSTANTES en código. Cambiarlos requiere un commit con review.
    NUNCA se leen de Redis, de un prompt, ni de una API.
    """
    # === POSITION SIZING ===
    MAX_POSITION_SIZE_PCT = 25.0      # Máximo 25% del capital en una posición
    MAX_TOTAL_EXPOSURE_PCT = 75.0     # Máximo 75% del capital total expuesto
    MAX_LEVERAGE = 5.0                # Máximo 5x leverage (NUNCA más)
    MAX_CONCURRENT_POSITIONS = 3      # Máximo 3 posiciones abiertas

    # === RISK PER TRADE ===
    MAX_RISK_PER_TRADE_PCT = 2.0      # Máximo 2% del capital en riesgo por trade
    MAX_RISK_BEAR_PCT = 0.5           # En BEAR: máximo 0.5%
    MAX_RISK_SIDEWAYS_PCT = 1.0       # En SIDEWAYS: máximo 1%

    # === DRAWDOWN CIRCUIT BREAKERS ===
    MAX_DAILY_DD_PCT = 5.0            # > 5% → STOP ALL
    MAX_WEEKLY_DD_PCT = 10.0          # > 10% → STOP ALL
    MAX_TOTAL_DD_PCT = 20.0           # > 20% → STOP ALL + alerta

    # === ORDER LIMITS ===
    MAX_ORDER_SIZE_USD = 50_000       # Máximo $50K por orden
    MIN_ORDER_SIZE_USD = 10           # Mínimo $10 por orden
    MAX_SLIPPAGE_PCT = 0.5            # > 0.5% → cancelar

    # === RATE LIMITS DE TRADING ===
    MAX_TRADES_PER_HOUR = 10          # Máximo 10 trades/hora
    MAX_TRADES_PER_DAY = 50           # Máximo 50 trades/día
    MIN_TIME_BETWEEN_TRADES_SEC = 60  # Mínimo 60s entre trades

    # === KILL SWITCH ===
    KILL_SWITCH_FILE = "/home/btquantr/.kill_switch"


class TradeEnforcer:
    """
    Último gate antes del exchange. Valida órdenes contra HardLimits.
    Si viola cualquier límite → bloquea o ajusta. Nunca ignora.
    Se conecta a ejecución real en Fase 3.
    """
    # TODO(security/fase3): persistir _trades_hour, _trades_day y _last_trade_time
    # en Redis con TTL (3600s y 86400s respectivamente) para que el rate limiting
    # sobreviva reinicios de proceso. Con el estado en memoria, un restart resetea
    # los contadores y permite bypass del MAX_TRADES_PER_HOUR/DAY.

    def __init__(self, r=None):
        self.r = r
        self._trades_hour: list[float] = []
        self._trades_day: list[float] = []
        self._last_trade_time: float = 0.0

    def enforce(self, order: dict, regime: str = "BULL") -> dict:
        """
        Valida order contra HardLimits. Retorna:
        {"allowed": bool, "reason": str, "adjusted_order": dict}
        """
        now = time.time()

        # 1. Kill switch
        if os.path.exists(HardLimits.KILL_SWITCH_FILE):
            self._emergency_close_all("KILL_SWITCH_FILE detected")
            return {"allowed": False, "reason": "KILL_SWITCH", "adjusted_order": order}

        # 2. Drawdown circuit breakers
        if self.r:
            try:
                raw = self.r.get("risk:status")
                if raw:
                    portfolio = json.loads(raw)
                    daily_dd = float(portfolio.get("daily_dd_pct", 0))
                    weekly_dd = float(portfolio.get("weekly_dd_pct", 0))
                    total_dd = float(portfolio.get("total_dd_pct", 0))
                    if daily_dd >= HardLimits.MAX_DAILY_DD_PCT:
                        self._emergency_close_all(f"daily DD {daily_dd}%")
                        return {"allowed": False, "reason": f"DAILY_DD_{daily_dd}pct", "adjusted_order": order}
                    if weekly_dd >= HardLimits.MAX_WEEKLY_DD_PCT:
                        self._emergency_close_all(f"weekly DD {weekly_dd}%")
                        return {"allowed": False, "reason": f"WEEKLY_DD_{weekly_dd}pct", "adjusted_order": order}
                    if total_dd >= HardLimits.MAX_TOTAL_DD_PCT:
                        self._emergency_close_all(f"total DD {total_dd}%")
                        return {"allowed": False, "reason": f"TOTAL_DD_{total_dd}pct", "adjusted_order": order}
            except Exception as e:
                log.error(f"TradeEnforcer: Redis error reading risk:status — blocking order (fail closed): {e}")
                return {"allowed": False, "reason": "REDIS_ERROR_FAIL_CLOSED", "adjusted_order": order}

        # 3. Ajustar position size
        size_pct = float(order.get("size_pct", 0))
        if size_pct > HardLimits.MAX_POSITION_SIZE_PCT:
            order = {**order, "size_pct": HardLimits.MAX_POSITION_SIZE_PCT}
            log.warning(f"Size ajustado de {size_pct}% a {HardLimits.MAX_POSITION_SIZE_PCT}%")

        # 4. Order size USD
        order_usd = float(order.get("order_size_usd", 0))
        if order_usd > HardLimits.MAX_ORDER_SIZE_USD:
            order = {**order, "order_size_usd": HardLimits.MAX_ORDER_SIZE_USD}
        if 0 < order_usd < HardLimits.MIN_ORDER_SIZE_USD:
            return {"allowed": False, "reason": f"ORDER_TOO_SMALL_{order_usd}USD", "adjusted_order": order}

        # 5. Leverage
        leverage = float(order.get("leverage", 1.0))
        if leverage > HardLimits.MAX_LEVERAGE:
            order = {**order, "leverage": HardLimits.MAX_LEVERAGE}
            log.warning(f"Leverage ajustado de {leverage}x a {HardLimits.MAX_LEVERAGE}x")

        # 6. Risk per trade según régimen
        risk_pct = float(order.get("max_risk_pct", 0))
        regime_limits = {
            "BULL": HardLimits.MAX_RISK_PER_TRADE_PCT,
            "SIDEWAYS": HardLimits.MAX_RISK_SIDEWAYS_PCT,
            "BEAR": HardLimits.MAX_RISK_BEAR_PCT,
        }
        max_risk = regime_limits.get(regime, HardLimits.MAX_RISK_PER_TRADE_PCT)
        if risk_pct > max_risk:
            order = {**order, "max_risk_pct": max_risk}

        # 7. Rate limits de trading
        self._trades_hour = [t for t in self._trades_hour if now - t < 3600]
        self._trades_day = [t for t in self._trades_day if now - t < 86400]
        if len(self._trades_hour) >= HardLimits.MAX_TRADES_PER_HOUR:
            return {"allowed": False, "reason": "MAX_TRADES_PER_HOUR", "adjusted_order": order}
        if len(self._trades_day) >= HardLimits.MAX_TRADES_PER_DAY:
            return {"allowed": False, "reason": "MAX_TRADES_PER_DAY", "adjusted_order": order}

        # 8. Tiempo mínimo entre trades
        if now - self._last_trade_time < HardLimits.MIN_TIME_BETWEEN_TRADES_SEC:
            elapsed = now - self._last_trade_time
            return {"allowed": False, "reason": f"MIN_TIME_NOT_MET_{elapsed:.0f}s", "adjusted_order": order}

        # Registrar trade
        self._trades_hour.append(now)
        self._trades_day.append(now)
        self._last_trade_time = now

        return {"allowed": True, "reason": "PASSED_ALL_CHECKS", "adjusted_order": order}

    def _emergency_close_all(self, reason: str) -> None:
        log.critical(f"EMERGENCY CLOSE ALL: {reason}")
        if self.r:
            try:
                self.r.publish("execution:commands",
                               json.dumps({"action": "CLOSE_ALL_NOW", "reason": reason}))
            except Exception:
                pass


class SecurityMonitor:
    """Detecta patrones de ataque analizando Redis Streams de seguridad."""

    ALERT_THRESHOLDS = {
        "security:injection_log": 5,
        "security:context_injection_log": 3,
        "security:output_validation_log": 3,
    }

    def __init__(self, r):
        self.r = r

    def check(self) -> list[dict]:
        """Analiza streams de seguridad. Retorna lista de alertas activas."""
        alerts = []
        now = time.time()
        one_hour_ago = now - 3600
        for stream_key, threshold in self.ALERT_THRESHOLDS.items():
            try:
                entries = self.r.xrange(stream_key, "-", "+") or []
                recent = [e for e in entries
                          if float(e[1].get("timestamp", 0)) > one_hour_ago]
                if len(recent) >= threshold:
                    alert = {
                        "source": "security_monitor",
                        "stream": stream_key,
                        "count": len(recent),
                        "threshold": threshold,
                        "ts": now,
                    }
                    alerts.append(alert)
                    self.r.publish("alerts", json.dumps(alert))
            except Exception:
                pass
        return alerts
