"""
btquantr/execution/router.py — ExecutionRouter.

Detecta el tipo de símbolo y redirige órdenes al conector correcto:
  - Crypto (*USDT, xyz:*) → HLConnector
  - Forex / Stock (EURUSD, SPY, etc.) → MT5Connector
  - Dry-run por defecto: no ejecuta órdenes reales sin --live / dry_run=False.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("BTQUANTRrouter")

# Símbolos forex y stocks conocidos (mismos que en evolution_loop)
_FOREX_SYMBOLS = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"}
_STOCK_SYMBOLS = {"SPY", "GLD", "AAPL"}
_MT5_SYMBOLS   = _FOREX_SYMBOLS | _STOCK_SYMBOLS


def _is_crypto(symbol: str) -> bool:
    """Retorna True si el símbolo es crypto (USDT suffix o HIP3 xyz:coin)."""
    s = symbol.upper()
    return s.endswith("USDT") or ":" in symbol


def _is_mt5(symbol: str) -> bool:
    """Retorna True si el símbolo pertenece a forex o stocks conocidos."""
    return symbol.upper() in _MT5_SYMBOLS


class ExecutionRouter:
    """Enrutador de órdenes que selecciona HLConnector o MT5Connector.

    Parámetros:
        hl_connector:  HLConnector conectado (o None).
        mt5_connector: MT5Connector conectado (o None).
        dry_run:       Si True (default), simula órdenes sin enviarlas.

    Uso:
        router = ExecutionRouter(hl_connector=hl, mt5_connector=mt5, dry_run=False)
        result = router.send_order("BTCUSDT", "BUY", size=0.1)
        positions = router.get_all_positions()
    """

    def __init__(
        self,
        hl_connector=None,
        mt5_connector=None,
        dry_run: bool = True,
        circuit_breakers=None,
        position_sizer=None,
    ) -> None:
        self.hl  = hl_connector
        self.mt5 = mt5_connector
        self.dry_run = dry_run
        self.circuit_breakers = circuit_breakers
        self.position_sizer = position_sizer

    # ── Routing ───────────────────────────────────────────────────────────

    def route(self, symbol: str) -> str:
        """Retorna "hl" o "mt5" según el tipo de símbolo."""
        if _is_mt5(symbol):
            return "mt5"
        return "hl"

    # ── send_order ────────────────────────────────────────────────────────

    def stop_all(self) -> dict:
        """Cierra todas las posiciones en todos los conectores (STOP_ALL global).

        Llamado cuando MaxDrawdown se activa o se requiere parada de emergencia.

        Returns:
            {"stopped": [{"source": str, "symbol": str, "result": dict}, ...]}
        """
        stopped = []

        if self.hl is not None and self.hl.is_connected:
            for pos in self.hl.get_positions():
                symbol = pos.get("symbol", "")
                if symbol:
                    result = self.hl.close_position(symbol)
                    stopped.append({"source": "hl", "symbol": symbol, "result": result})
                    log.warning("STOP_ALL: closed HL %s → %s", symbol, result)

        if self.mt5 is not None and self.mt5.is_connected:
            for pos in self.mt5.get_positions():
                symbol = pos.get("symbol", "")
                ticket = pos.get("ticket")
                if ticket:
                    result = self.mt5.close_position(ticket)
                elif symbol:
                    result = self.mt5.close_position(symbol)
                else:
                    continue
                stopped.append({"source": "mt5", "symbol": symbol, "result": result})
                log.warning("STOP_ALL: closed MT5 %s → %s", symbol, result)

        log.warning("STOP_ALL completed: %d positions closed", len(stopped))
        return {"stopped": stopped}

    def send_order(
        self,
        symbol: str,
        direction: str,
        size: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        portfolio: Optional[dict] = None,
        n_open_positions: int = 0,
    ) -> dict:
        """Envía una orden al conector correcto.

        En dry_run=True retorna un dict simulado sin llamar a ningún conector.

        Returns:
            En dry-run: {"dry_run": True, "symbol": str, "direction": str,
                         "size": float, "connector": str}
            En live:    Resultado del conector ({"success": bool, ...})
        """
        connector_name = self.route(symbol)

        # Verificar circuit breakers antes de procesar la orden
        if self.circuit_breakers is not None:
            cb_result = self.circuit_breakers.check_all(portfolio or {}, n_open_positions)
            if not cb_result["allowed"]:
                log.warning(
                    "Order BLOCKED by circuit breaker: %s", cb_result["tripped_by"]
                )
                return {
                    "blocked": True,
                    "reason": "CIRCUIT_BREAKER",
                    "tripped_by": cb_result["tripped_by"],
                }

        if self.dry_run:
            log.info("[DRY-RUN] %s %s size=%s → %s", direction, symbol, size, connector_name)
            return {
                "dry_run":   True,
                "symbol":    symbol,
                "direction": direction,
                "size":      size,
                "connector": connector_name,
            }

        # Live: selecciona conector
        connector = self.hl if connector_name == "hl" else self.mt5
        if connector is None:
            return {"success": False, "error": f"no {connector_name} connector configured"}

        return connector.send_order(symbol, direction, size, sl=sl, tp=tp)

    # ── send_order_auto (con PositionSizer) ───────────────────────────────

    def send_order_auto(
        self,
        symbol: str,
        direction: str,
        balance: float,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        regime: str = "BULL",
        atr: Optional[float] = None,
        atr_mean: Optional[float] = None,
        open_exposure_usd: float = 0.0,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        portfolio: Optional[dict] = None,
        n_open_positions: int = 0,
    ) -> dict:
        """Calcula el tamaño con PositionSizer y envía la orden.

        Requiere que position_sizer esté configurado en el router.

        Returns:
            En éxito:  resultado de send_order + campos del sizer.
            En blocked: {"blocked": True, "reason": ..., "size_usd": 0}.
            Sin sizer:  {"blocked": True, "error": "no position_sizer configured"}.
        """
        if self.position_sizer is None:
            log.error("send_order_auto: no position_sizer configurado en el router")
            return {"blocked": True, "error": "no position_sizer configured"}

        sizing = self.position_sizer.calculate(
            balance=balance,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            regime=regime,
            atr=atr,
            atr_mean=atr_mean,
            open_exposure_usd=open_exposure_usd,
        )

        if sizing["blocked"]:
            log.warning(
                "send_order_auto BLOCKED by PositionSizer: %s", sizing["reason"]
            )
            return {
                "blocked": True,
                "reason": "POSITION_SIZER_BLOCKED",
                "size_usd": 0.0,
                "size_pct": 0.0,
                "kelly_fraction": sizing["kelly_fraction"],
                "regime_scale": sizing["regime_scale"],
                "atr_scale": sizing["atr_scale"],
            }

        size = sizing["size_usd"]
        order_result = self.send_order(
            symbol=symbol,
            direction=direction,
            size=size,
            sl=sl,
            tp=tp,
            portfolio=portfolio,
            n_open_positions=n_open_positions,
        )

        # Fusionar resultado de la orden con metadatos del sizing
        return {
            **order_result,
            "size_usd":       size,
            "size":           size,
            "size_pct":       sizing["size_pct"],
            "kelly_fraction": sizing["kelly_fraction"],
            "regime_scale":   sizing["regime_scale"],
            "atr_scale":      sizing["atr_scale"],
            "capped_by":      sizing["capped_by"],
        }

    # ── get_all_positions ─────────────────────────────────────────────────

    def get_all_positions(self) -> list[dict]:
        """Agrega posiciones de todos los conectores conectados.

        Cada posición lleva un campo "source": "hl" | "mt5".
        """
        positions: list[dict] = []

        if self.hl is not None and self.hl.is_connected:
            for p in self.hl.get_positions():
                positions.append({**p, "source": "hl"})

        if self.mt5 is not None and self.mt5.is_connected:
            for p in self.mt5.get_positions():
                positions.append({**p, "source": "mt5"})

        return positions
