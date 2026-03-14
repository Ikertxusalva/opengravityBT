"""HIP3 Liquidation Cascade — estrategia backtesting.py para activos sintéticos HIP3.

Lógica de entrada:
  LONG  → shorts near liq >= $250k + momentum alcista (EMA slope + RSI)
  SHORT → longs near liq >= $250k + momentum bajista  (EMA slope + RSI)

Para backtesting: usa EMA slope + RSI como proxy de la señal de liquidación.
Para live trading: conectar HLPositionsSource.get_cascade_signal() antes de next().

TP: 1.5%, SL: 1.0%, max hold: 2 barras (a 1h = 2 horas).
"""
from __future__ import annotations

import numpy as np
import pandas_ta as ta

from rbi.strategies.base import RBIStrategy


class HIP3LiquidationCascade(RBIStrategy):
    """Liquidation Cascade para HIP3 — activos sintéticos HyperLiquid.

    Parámetros:
        ema_period:           Período EMA para detectar momentum.
        rsi_period:           Período RSI.
        rsi_long_threshold:   RSI mínimo para señal LONG (shorts atrapados).
        rsi_short_threshold:  RSI máximo para señal SHORT (longs atrapados).
        min_notional:         USD mínimo near-liq para activar señal (live trading).
        tp_pct:               Take profit porcentual (1.5%).
        sl_pct:               Stop loss porcentual (1.0%).
        max_hold_bars:        Barras máximas de retención (2 barras = 2h en 1h TF).
    """

    strategy_name = "HIP3 Liquidation Cascade"
    strategy_type = "Liquidation Hunting"

    ema_period          = 20
    rsi_period          = 14
    rsi_long_threshold  = 55    # RSI > 55: momentum alcista, shorts atrapados
    rsi_short_threshold = 45    # RSI < 45: momentum bajista, longs atrapados
    min_notional        = 250_000  # USD near liq para señal (live)
    tp_pct              = 0.015    # 1.5% take profit
    sl_pct              = 0.010    # 1.0% stop loss
    max_hold_bars       = 2        # máx 2 barras antes de cerrar por tiempo

    def init(self):
        n = len(self.data)
        _nan = np.full(n, np.nan)

        ema_raw = ta.ema(self.close, length=self.ema_period)
        rsi_raw = ta.rsi(self.close, length=self.rsi_period)

        ema_arr = ema_raw.values if ema_raw is not None else _nan
        rsi_arr = rsi_raw.values if rsi_raw is not None else _nan

        self.ema = self.I(lambda: ema_arr, name="EMA")
        self.rsi = self.I(lambda: rsi_arr, name="RSI")
        self._entry_bar = 0

    def next(self):
        warmup = max(self.ema_period, self.rsi_period) + 2
        if len(self.data) < warmup:
            return

        if np.isnan(self.ema[-1]) or np.isnan(self.ema[-2]) or np.isnan(self.rsi[-1]):
            return

        # ── Cerrar por max hold ───────────────────────────────────────────────
        if self.position and self._entry_bar > 0:
            bars_held = len(self.data) - self._entry_bar
            if bars_held >= self.max_hold_bars:
                self.position.close()
                self._entry_bar = 0
                return

        price     = self.data.Close[-1]
        ema_slope = self.ema[-1] - self.ema[-2]   # positivo = tendencia alcista
        rsi_val   = self.rsi[-1]

        if not self.position:
            # ── LONG: shorts trapped near liq + momentum alcista ──────────────
            # Proxy: EMA slope > 0 y RSI > rsi_long_threshold
            if ema_slope > 0 and rsi_val > self.rsi_long_threshold:
                self.buy(
                    sl=price * (1 - self.sl_pct),
                    tp=price * (1 + self.tp_pct),
                )
                self._entry_bar = len(self.data)

            # ── SHORT: longs trapped near liq + momentum bajista ──────────────
            # Proxy: EMA slope < 0 y RSI < rsi_short_threshold
            elif ema_slope < 0 and rsi_val < self.rsi_short_threshold:
                self.sell(
                    sl=price * (1 + self.sl_pct),
                    tp=price * (1 - self.tp_pct),
                )
                self._entry_bar = len(self.data)
