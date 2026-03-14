"""
btquantr/execution/mt5_connector.py — Conector Python ↔ MetaTrader5.

Wrapper sobre la librería oficial MetaTrader5 (solo disponible en Windows
con MT5 abierto). Todos los métodos levantan RuntimeError si MT5 no está
conectado.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("BTQUANTRmt5")


class MT5Connector:
    """Conector directo con MetaTrader5 vía la librería oficial.

    Uso:
        conn = MT5Connector()
        conn.connect()
        info = conn.get_account_info()
        conn.send_order("BTCUSD", "BUY", lot_size=0.1)
        conn.disconnect()
    """

    def __init__(self) -> None:
        self.is_connected: bool = False

    # ── Ciclo de vida ──────────────────────────────────────────────────────

    def connect(
        self,
        login: Optional[int] = None,
        server: Optional[str] = None,
        password: Optional[str] = None,
    ) -> bool:
        """Inicializa la conexión con MT5.

        Returns:
            True si la conexión fue exitosa, False en caso contrario.
        """
        import MetaTrader5 as mt5

        kwargs: dict = {}
        if login is not None:
            kwargs["login"] = login
        if server is not None:
            kwargs["server"] = server
        if password is not None:
            kwargs["password"] = password

        ok = mt5.initialize(**kwargs)
        self.is_connected = bool(ok)
        return self.is_connected

    def disconnect(self) -> None:
        """Cierra la conexión con MT5."""
        import MetaTrader5 as mt5

        mt5.shutdown()
        self.is_connected = False

    # ── Cuenta ────────────────────────────────────────────────────────────

    def get_account_info(self) -> Optional[dict]:
        """Retorna información de la cuenta o None si MT5 falla."""
        import MetaTrader5 as mt5

        acc = mt5.account_info()
        if acc is None:
            return None
        return {
            "login":    acc.login,
            "server":   acc.server,
            "balance":  acc.balance,
            "equity":   acc.equity,
            "margin":   acc.margin,
            "currency": acc.currency,
        }

    # ── Posiciones ────────────────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """Retorna lista de posiciones abiertas."""
        import MetaTrader5 as mt5

        raw = mt5.positions_get()
        if not raw:
            return []
        result = []
        for p in raw:
            direction = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
            result.append({
                "ticket":        p.ticket,
                "symbol":        p.symbol,
                "direction":     direction,
                "volume":        p.volume,
                "price_open":    p.price_open,
                "price_current": p.price_current,
                "profit":        p.profit,
                "sl":            p.sl,
                "tp":            p.tp,
            })
        return result

    # ── Envío de órdenes ──────────────────────────────────────────────────

    def send_order(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> dict:
        """Envía una orden de mercado a MT5.

        Args:
            symbol:    Símbolo (ej. "BTCUSD", "EURUSD")
            direction: "BUY" o "SELL"
            lot_size:  Tamaño del lote
            sl:        Stop Loss (opcional)
            tp:        Take Profit (opcional)

        Returns:
            {"success": bool, "order_id": int, "retcode": int}
        """
        import MetaTrader5 as mt5

        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if direction.upper() == "BUY" else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL

        request: dict = {
            "action":      mt5.TRADE_ACTION_DEAL,
            "symbol":      symbol,
            "volume":      lot_size,
            "type":        order_type,
            "price":       price,
            "type_time":   mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl is not None:
            request["sl"] = sl
        if tp is not None:
            request["tp"] = tp

        res = mt5.order_send(request)
        success = res.retcode == mt5.RES_S_OK
        return {
            "success":  success,
            "order_id": res.order,
            "retcode":  res.retcode,
        }

    # ── Cerrar posición ───────────────────────────────────────────────────

    def close_position(self, ticket: int) -> dict:
        """Cierra una posición abierta por ticket.

        Returns:
            {"success": bool, "order_id": int} o {"success": False, "error": str}
        """
        import MetaTrader5 as mt5

        positions = mt5.positions_get()
        if not positions:
            return {"success": False, "error": f"position {ticket} not found"}

        pos = next((p for p in positions if p.ticket == ticket), None)
        if pos is None:
            return {"success": False, "error": f"position {ticket} not found"}

        # Cierre inverso: long → SELL, short → BUY
        if pos.type == mt5.POSITION_TYPE_BUY:
            close_type = mt5.ORDER_TYPE_SELL
            tick = mt5.symbol_info_tick(pos.symbol)
            price = tick.bid
        else:
            close_type = mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(pos.symbol)
            price = tick.ask

        request = {
            "action":      mt5.TRADE_ACTION_DEAL,
            "symbol":      pos.symbol,
            "volume":      pos.volume,
            "type":        close_type,
            "price":       price,
            "position":    ticket,
            "type_time":   mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(request)
        success = res.retcode == mt5.RES_S_OK
        return {
            "success":  success,
            "order_id": res.order,
            "retcode":  res.retcode,
        }
