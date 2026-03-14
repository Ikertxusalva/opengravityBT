"""
btquantr/engine/signal_engine.py — SignalEngine.

Genera señales localmente desde StrategyStore sin API Claude.
Carga la mejor estrategia para symbol×regime, corre los últimos 200 candles
con finalize_trades=False y detecta si hay posición abierta en la última barra.
$0 operativo.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from backtesting import Backtest

from btquantr.engine.strategy_store import StrategyStore

log = logging.getLogger("BTQUANTRSignalEngine")


class SignalEngine:
    """Genera señales de trading localmente sin API Claude.

    Flujo:
      1. get_best(symbol, regime) → strategy dict
      2. _run_on_ohlcv(strategy, ohlcv.tail(WINDOW)) → {action, reason}
      3. Mapea BUY/SELL/HOLD con confidence basada en fitness
    """

    WINDOW = 200

    def __init__(
        self,
        store: Optional[StrategyStore] = None,
        mt5_connector=None,
    ) -> None:
        self.store = store or StrategyStore()
        self.mt5_connector = mt5_connector

    def get_signal(self, symbol: str, regime: str, ohlcv: Optional[pd.DataFrame]) -> dict:
        """Genera señal de trading sin API.

        Returns:
            {
                "action": "BUY" | "SELL" | "HOLD",
                "confidence": float,  # 0-100
                "reason": str,
                "strategy_name": str | None,
                "source": "autonomous"
            }
        """
        strategy = self.store.get_best(symbol, regime)
        if strategy is None:
            return self._hold("no strategy registered")

        if ohlcv is None or len(ohlcv) == 0:
            return self._hold("no OHLCV data")

        data = ohlcv.tail(self.WINDOW)
        result = self._run_on_ohlcv(strategy, data)

        action = result.get("action", "HOLD")
        fitness = strategy.get("fitness", 0.0)

        if action == "BUY":
            confidence = round(min(100.0, fitness * 100), 1)
        elif action == "SELL":
            confidence = round(min(100.0, fitness * 80), 1)
        else:
            confidence = 0.0

        return {
            "action": action,
            "confidence": confidence,
            "reason": result.get("reason", ""),
            "strategy_name": strategy.get("name") if action != "HOLD" else None,
            "source": "autonomous",
        }

    def _run_on_ohlcv(self, strategy: dict, ohlcv: pd.DataFrame) -> dict:
        """Corre la estrategia sobre ohlcv con finalize_trades=False.

        Detecta si hay posición abierta en la última barra via bt._broker.trades.

        Returns:
            {"action": "BUY"|"SELL"|"HOLD", "reason": str}
        """
        from btquantr.engine.evolution_loop import (
            _parameterize_class,
            _resolve_strategy_class,
        )

        cls = _resolve_strategy_class(strategy)
        if cls is None:
            return {"action": "HOLD", "reason": "strategy class not resolved"}

        cls = _parameterize_class(cls, strategy.get("params", {}))
        max_price = float(ohlcv["Close"].max())
        cash = max(10_000, max_price * 3)

        try:
            bt = Backtest(
                ohlcv,
                cls,
                cash=cash,
                commission=0.0004,
                exclusive_orders=True,
                finalize_trades=False,
            )
            stats = bt.run()
            # broker lives on the strategy instance stored in stats._strategy
            strat_instance = getattr(stats, "_strategy", None)
            broker = getattr(strat_instance, "_broker", None)
            open_trades = getattr(broker, "trades", [])
            if open_trades:
                trade = open_trades[-1]
                size = getattr(trade, "size", 0)
                entry_bar = getattr(trade, "entry_bar", -1)
                action = "BUY" if size > 0 else "SELL"
                return {
                    "action": action,
                    "reason": f"open_position size={size:.4f} entry_bar={entry_bar}",
                }
            return {"action": "HOLD", "reason": "no open position on last bar"}
        except Exception as exc:
            log.debug("_run_on_ohlcv error: %s", exc)
            return {"action": "HOLD", "reason": f"backtest error: {exc}"}

    def execute_signal(
        self,
        symbol: str,
        regime: str,
        ohlcv: Optional[pd.DataFrame],
        lot_size: float = 0.1,
    ) -> dict:
        """Genera señal y, si hay MT5Connector conectado, envía la orden.

        Returns:
            El dict de señal (igual que get_signal), con "mt5_order" si se ejecutó.
        """
        signal = self.get_signal(symbol, regime, ohlcv)
        action = signal.get("action", "HOLD")

        if self.mt5_connector is not None and action in ("BUY", "SELL"):
            order_result = self.mt5_connector.send_order(
                symbol, action, lot_size=lot_size
            )
            signal["mt5_order"] = order_result
            log.info(
                "MT5 order sent: %s %s → %s", action, symbol, order_result
            )

        return signal

    def _hold(self, reason: str) -> dict:
        return {
            "action": "HOLD",
            "confidence": 0.0,
            "reason": reason,
            "strategy_name": None,
            "source": "autonomous",
        }
