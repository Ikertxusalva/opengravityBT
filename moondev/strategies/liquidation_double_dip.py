"""
LiquidationDoubleDip — Variante 3: Wait for Rebound, Buy Pico Bottom.

Explota cascadas de liquidación esperando el double dip pattern:
  1. Liquidación inicial (volume spike + caída fuerte) → NO entrar
  2. Rebound (precio sube desde fondo)
  3. Retest (precio retesta fondo ≈ segundo dip)
  4. ENTRADA en el retest con confirmación (bounce bar + RSI oversold + trend filter)

Proxy de liquidaciones via OHLCV (volume spike > Nσ + drop% + RSI oversold).
SL/TP dinámicos basados en ATR para adaptarse a la volatilidad del activo.
Filtro de tendencia (SMA) para evitar comprar dips en tendencia bajista.

Fuente: PvTKTQikbEY — "I Found a Strategy That Makes Buy & Hold Look Like a Joke"
Sharpe esperado: 0.6-1.2 (post walk-forward)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy
from backtesting.test import SMA


class LiquidationDoubleDip(Strategy):
    vol_sigma = 15         # ÷10 → 1.5 sigmas para volume spike
    drop_threshold = 10    # ÷10 → 1.0% caída mínima
    rsi_threshold = 42     # RSI oversold para detectar liquidación
    rebound_pct = 10       # ÷10 → 1.0% mínimo rebound desde liq_low
    retest_tolerance = 15  # ÷10 → 1.5% tolerancia al retest del fondo
    sl_atr_mult = 15       # ÷10 → 1.5x ATR para stop loss
    tp_atr_mult = 30       # ÷10 → 3.0x ATR para take profit
    max_hold = 72          # barras máximas de hold antes de timeout
    vol_window = 20        # ventana para media/std de volumen
    trend_period = 100     # SMA period para filtro de tendencia

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high = pd.Series(self.data.High, index=range(len(self.data.High)))
        low = pd.Series(self.data.Low, index=range(len(self.data.Low)))
        volume = pd.Series(self.data.Volume, index=range(len(self.data.Volume)))

        self.rsi = self.I(
            lambda: ta.rsi(close, length=14).fillna(50).values,
            name="RSI",
        )

        self.atr = self.I(
            lambda: ta.atr(high, low, close, length=14).fillna(0).values,
            name="ATR",
        )

        self.sma_trend = self.I(SMA, self.data.Close, self.trend_period)

        vol_mean = volume.rolling(self.vol_window, min_periods=5).mean().fillna(0)
        vol_std = volume.rolling(self.vol_window, min_periods=5).std().fillna(0)
        self._vol_mean = self.I(lambda: vol_mean.values, name="VolMean")
        self._vol_std = self.I(lambda: vol_std.values, name="VolStd")

        # State machine
        self._liq_detected = False
        self._liq_low = 0.0
        self._rebound_seen = False
        self._entry_bar = 0
        self._liq_bar = 0

    def next(self):
        if len(self.data) < max(self.vol_window, self.trend_period) + 15:
            return

        price = self.data.Close[-1]
        low_val = self.data.Low[-1]
        open_ = self.data.Open[-1]
        vol = self.data.Volume[-1]
        rsi = self.rsi[-1]
        atr = self.atr[-1]
        vol_mean = self._vol_mean[-1]
        vol_std = self._vol_std[-1]
        sma = self.sma_trend[-1]

        if np.isnan(rsi) or np.isnan(vol_mean) or np.isnan(vol_std) or np.isnan(atr) or np.isnan(sma):
            return
        if atr <= 0:
            return

        sigma = float(self.vol_sigma) / 10.0
        drop_thr = float(self.drop_threshold) / 10.0 / 100.0
        rebound = float(self.rebound_pct) / 10.0 / 100.0
        tolerance = float(self.retest_tolerance) / 10.0 / 100.0
        sl_mult = float(self.sl_atr_mult) / 10.0
        tp_mult = float(self.tp_atr_mult) / 10.0

        bar = len(self.data)

        # --- Posición abierta: timeout check ---
        if self.position:
            if bar - self._entry_bar >= self.max_hold:
                self.position.close()
            return

        # --- State machine: detect → rebound → retest → entry ---

        # Step 1: Detect liquidación inicial
        if not self._liq_detected:
            vol_spike = (vol > vol_mean + sigma * vol_std) if vol_std > 0 else False
            strong_drop = ((open_ - price) / open_ > drop_thr) if open_ > 0 else False
            oversold = rsi < self.rsi_threshold

            if vol_spike and strong_drop and oversold:
                self._liq_detected = True
                self._liq_low = low_val
                self._rebound_seen = False
                self._liq_bar = bar
            return

        # Timeout
        if bar - self._liq_bar > self.max_hold * 3:
            self._reset_state()
            return

        # Step 2: Esperar rebound
        if not self._rebound_seen:
            if low_val < self._liq_low:
                self._liq_low = low_val
            if self._liq_low > 0 and price > self._liq_low * (1 + rebound):
                self._rebound_seen = True
            return

        # Step 3: Retest + entry conditions
        if self._liq_low > 0:
            near_liq = abs(low_val - self._liq_low) / self._liq_low <= tolerance
            bounce_bar = price > open_
            rsi_oversold_retest = rsi < self.rsi_threshold + 10
            trend_ok = price > sma * 0.97  # allow slight dip below SMA

            if near_liq and bounce_bar and rsi_oversold_retest and trend_ok:
                entry = price
                sl_price = entry - atr * sl_mult
                tp_price = entry + atr * tp_mult
                if sl_price > 0 and sl_price < entry < tp_price:
                    self.buy(size=0.95, sl=sl_price, tp=tp_price)
                    self._entry_bar = bar
                self._reset_state()
            elif low_val < self._liq_low * (1 - tolerance * 2):
                self._reset_state()

    def _reset_state(self):
        self._liq_detected = False
        self._liq_low = 0.0
        self._rebound_seen = False


if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    print("\n== LiquidationDoubleDip -- BTC 1h 365d ==\n")
    df = get_ohlcv("BTC", interval="1h", days=365)
    if df is None or len(df) < 100:
        print("ERROR: Sin datos suficientes")
        sys.exit(1)

    print(f"Datos: {len(df)} barras, {df.index[0]} -> {df.index[-1]}")
    cash = max(10_000, float(df["Close"].max()) * 3)
    print(f"Cash inicial: ${cash:,.0f}")

    bt = Backtest(df, LiquidationDoubleDip, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()

    print("\n" + "-" * 50)
    print("RESULTADOS:")
    print("-" * 50)
    print(stats[["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]",
                 "# Trades", "Win Rate [%]"]])
    print("-" * 50)

    pf = stats.get("Profit Factor", "N/A")
    avg_trade = stats.get("Avg. Trade [%]", "N/A")
    print(f"Profit Factor: {pf}")
    print(f"Avg Trade [%]: {avg_trade}")

    sharpe = float(stats["Sharpe Ratio"]) if pd.notna(stats["Sharpe Ratio"]) else 0.0
    dd = float(stats["Max. Drawdown [%]"])
    trades = int(stats["# Trades"])
    wr = float(stats["Win Rate [%]"]) if pd.notna(stats["Win Rate [%]"]) else 0.0

    print(f"\nVeredicto rapido:")
    if sharpe >= 1.0 and dd >= -20 and trades >= 30 and wr >= 45:
        print("  APROBADO -- Sharpe, DD, trades y WR cumplen criterios")
    elif sharpe >= 0.5 and dd >= -35 and trades >= 10:
        print("  PRECAUCION -- metricas mixtas, requiere mas analisis")
    else:
        print("  RECHAZADO -- no cumple criterios minimos de viabilidad")
    print()
