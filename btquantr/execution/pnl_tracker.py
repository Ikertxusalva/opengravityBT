"""
btquantr/execution/pnl_tracker.py — PnLTracker.

Rastrea PnL mark-to-market de posiciones abiertas en tiempo real.

Fuentes de actualización:
  1. update_position(): llamada desde ExecutionRouter al abrir/cerrar posiciones.
  2. process_fill_event(): llamada desde el WebSocket de fills de HyperLiquid.
  3. update_mark_price(): llamada desde DataService (precios en Redis).

PnL mark-to-market:
  LONG:  (mark_price - entry_price) × size
  SHORT: (entry_price - mark_price) × size

Drift detection:
  Compara PnL real (MTM) con PnL esperado (calculado desde señales).
  has_drift = abs(drift) > drift_threshold.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

log = logging.getLogger("BTQUANTRPnLTracker")

_CLOSE_DIRS = {"Close Long", "Close Short", "Liquidation"}


class PnLTracker:
    """Tracker de PnL mark-to-market con detección de drift.

    Args:
        drift_threshold: USD de diferencia para considerar drift significativo.
    """

    def __init__(self, drift_threshold: float = 50.0) -> None:
        self.drift_threshold = drift_threshold
        # {symbol: {"side": "LONG"|"SHORT", "size": float, "entry_price": float}}
        self.positions: dict[str, dict] = {}
        # {symbol: float}
        self.mark_prices: dict[str, float] = {}

    # ── Actualización de posiciones ───────────────────────────────────────

    def update_position(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
    ) -> None:
        """Añade o actualiza una posición.

        Si size == 0, elimina la posición del tracker.
        """
        if size == 0.0:
            self.positions.pop(symbol, None)
            return
        self.positions[symbol] = {
            "side": side,
            "size": size,
            "entry_price": entry_price,
            "updated_at": time.time(),
        }

    def update_mark_price(self, symbol: str, price: float) -> None:
        """Actualiza el precio mark-to-market de un símbolo."""
        self.mark_prices[symbol] = price

    # ── WebSocket fills ───────────────────────────────────────────────────

    def process_fill_event(self, event: dict) -> None:
        """Procesa un evento fill del WebSocket de HyperLiquid.

        Formato del evento (simplificado):
            {
                "coin": "BTC",
                "px": "50000.0",   # precio de ejecución
                "sz": "0.1",       # tamaño
                "side": "A",       # A=Buy taker, B=Sell taker
                "dir": "Open Long" | "Close Long" | "Open Short" | "Close Short",
                "closedPnl": "0",
                ...
            }
        """
        try:
            coin = event.get("coin")
            if not coin:
                return
            direction = event.get("dir", "")
            if direction in _CLOSE_DIRS:
                self.positions.pop(coin, None)
                return
            px = float(event.get("px", 0))
            sz = float(event.get("sz", 0))
            side_raw = event.get("side", "A")
            side = "LONG" if side_raw == "A" else "SHORT"
            if sz > 0 and px > 0:
                self.update_position(coin, side, sz, px)
        except Exception as exc:
            log.debug("process_fill_event error: %s | event=%s", exc, event)

    # ── Mark-to-Market PnL ────────────────────────────────────────────────

    def calculate_mtm(self) -> dict[str, dict]:
        """Calcula PnL mark-to-market para todas las posiciones abiertas.

        Returns:
            {symbol: {
                "unrealized_pnl": float,
                "pnl_pct": float,         # % sobre valor de entrada
                "mark_price": float,
                "entry_price": float,
                "side": str,
                "size": float,
            }}
        """
        result: dict[str, dict] = {}
        for sym, pos in self.positions.items():
            entry = pos["entry_price"]
            size = pos["size"]
            side = pos["side"]
            mark = self.mark_prices.get(sym, entry)  # fallback a entry → PnL=0

            if side == "LONG":
                pnl = (mark - entry) * size
            else:  # SHORT
                pnl = (entry - mark) * size

            entry_value = entry * size
            pnl_pct = (pnl / entry_value * 100.0) if entry_value != 0 else 0.0

            result[sym] = {
                "unrealized_pnl": round(pnl, 6),
                "pnl_pct": round(pnl_pct, 4),
                "mark_price": mark,
                "entry_price": entry,
                "side": side,
                "size": size,
            }
        return result

    # ── Drift detection ───────────────────────────────────────────────────

    def detect_drift(self, expected_pnl: float) -> dict:
        """Compara PnL real (MTM) con PnL esperado.

        Args:
            expected_pnl: PnL que esperamos basado en nuestros cálculos de señales.

        Returns:
            {
                "drift": float,          # actual_pnl - expected_pnl
                "has_drift": bool,       # abs(drift) > drift_threshold
                "actual_pnl": float,
                "expected_pnl": float,
            }
        """
        mtm = self.calculate_mtm()
        actual_pnl = sum(v["unrealized_pnl"] for v in mtm.values())
        drift = actual_pnl - expected_pnl
        return {
            "drift": round(drift, 6),
            "has_drift": abs(drift) > self.drift_threshold,
            "actual_pnl": round(actual_pnl, 6),
            "expected_pnl": round(expected_pnl, 6),
        }

    # ── Resumen ───────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """Retorna resumen completo del estado actual del tracker.

        Returns:
            {
                "n_positions": int,
                "total_unrealized_pnl": float,
                "positions": {symbol: mtm_dict, ...},
            }
        """
        mtm = self.calculate_mtm()
        total_pnl = sum(v["unrealized_pnl"] for v in mtm.values())
        return {
            "n_positions": len(self.positions),
            "total_unrealized_pnl": round(total_pnl, 6),
            "positions": mtm,
        }
