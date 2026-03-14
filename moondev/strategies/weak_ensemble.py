"""
WeakEnsemble -- Agregacion de 10 senales debiles (inspirado en Renaissance Technologies).

v5 -- Gate de regimen explicito (SMA20/50 + ADX) para eliminar DD -40/-70%.

Problema de v1-v4: DD -40% a -70% en crypto. Causa: el ensemble no tenia barrera
ante mercados laterales/bajistas — seguia abriendo posiciones en ambas direcciones.

Cambios v5:
  - Regime gate: solo LONG si SMA20 > SMA50 AND ADX > regime_adx (BULL)
  - Regime gate: solo SHORT si SMA20 < SMA50 AND ADX > regime_adx (BEAR)
  - SIDEWAYS (ADX bajo): PROHIBIDO abrir trades nuevos
  - Cerrar posicion existente si regimen la contradice
  - Todo lo demas igual que v4

Cambios v4 (mantenidos):
  - Senales 1-8 son TREND-FOLLOWING (precio > media = +1, no RSI oversold)
  - Senales 9-10 son CONFIRMACION (volumen/volatilidad confirma direccion)
  - threshold=4 para entrar (4 de 10 = consenso moderado)
  - LONG si suma >= threshold, SHORT si suma <= -threshold
  - Salida: trailing via senal contraria (suma cruza 0)
  - SL/TP mas ajustados: sl=1.5 ATR, tp=2.5 ATR

Senales (todas trend-following):
  1. Precio > SMA(20) = +1, else -1
  2. Precio > SMA(50) = +1, else -1
  3. EMA(9) > EMA(21) = +1, else -1
  4. EMA(21) > EMA(50) = +1, else -1
  5. MACD > signal = +1, else -1
  6. Close > Close[-20] (momentum) = +1, else -1
  7. Close > Close[-5] (momentum corto) = +1, else -1
  8. ADX > 20 & +DI > -DI = +1, ADX > 20 & -DI > +DI = -1, else 0
  9. ATR expansion + direction = confirma
  10. Volume expansion + direction = confirma
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class WeakEnsemble(Strategy):
    # -- Parametros optimizables --
    threshold   = 4     # Suma >= 4 para entrar (4 de 10 senales)
    sl_mult     = 15    # x10: 15 = 1.5 ATR para stop loss
    tp_mult     = 25    # x10: 25 = 2.5 ATR para take profit
    atr_period  = 14
    vol_window  = 20
    # -- Regime gate (v5) --
    regime_adx       = 20   # ADX minimo para considerar tendencia valida (BULL/BEAR)
    regime_min_bars  = 12   # régimen debe persistir N barras antes de actuar (anti-churn)

    def init(self):
        close  = pd.Series(self.data.Close,  index=range(len(self.data.Close)))
        high   = pd.Series(self.data.High,   index=range(len(self.data.High)))
        low    = pd.Series(self.data.Low,    index=range(len(self.data.Low)))
        volume = pd.Series(self.data.Volume, index=range(len(self.data.Volume)))
        n = len(close)

        # Senal 1: Precio > SMA(20)
        sma20 = ta.sma(close, length=20).fillna(0)
        s1 = np.where(close > sma20, 1.0, -1.0)
        self.s1 = self.I(lambda: s1, name="S_SMA20")

        # Senal 2: Precio > SMA(50)
        sma50 = ta.sma(close, length=50).fillna(0)
        s2 = np.where(close > sma50, 1.0, -1.0)
        self.s2 = self.I(lambda: s2, name="S_SMA50")

        # Senal 3: EMA(9) > EMA(21)
        ema9  = ta.ema(close, length=9).fillna(0)
        ema21 = ta.ema(close, length=21).fillna(0)
        s3 = np.where(ema9 > ema21, 1.0, -1.0)
        self.s3 = self.I(lambda: s3, name="S_EMA9_21")

        # Senal 4: EMA(21) > EMA(50)
        ema50 = ta.ema(close, length=50).fillna(0)
        s4 = np.where(ema21 > ema50, 1.0, -1.0)
        self.s4 = self.I(lambda: s4, name="S_EMA21_50")

        # Senal 5: MACD > signal
        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        if macd_df is not None and macd_df.shape[1] >= 3:
            macd_line   = macd_df.iloc[:, 0].fillna(0)
            signal_line = macd_df.iloc[:, 2].fillna(0)
            s5 = np.where(macd_line > signal_line, 1.0, -1.0)
        else:
            s5 = np.zeros(n)
        self.s5 = self.I(lambda: s5, name="S_MACD")

        # Senal 6: Momentum 20 barras (Close > Close[-20])
        mom20 = close.pct_change(20).fillna(0)
        s6 = np.sign(mom20.values)
        self.s6 = self.I(lambda: s6, name="S_MOM20")

        # Senal 7: Momentum 5 barras (Close > Close[-5])
        mom5 = close.pct_change(5).fillna(0)
        s7 = np.sign(mom5.values)
        self.s7 = self.I(lambda: s7, name="S_MOM5")

        # Senal 8: ADX + DI (tendencia con direccion)
        adx_df = ta.adx(high, low, close, length=14)
        if adx_df is not None and adx_df.shape[1] >= 3:
            adx_vals = adx_df.iloc[:, 0].fillna(0)   # ADX
            dmp = adx_df.iloc[:, 1].fillna(0)          # DI+
            dmn = adx_df.iloc[:, 2].fillna(0)          # DI-
            s8 = np.zeros(n)
            s8[(adx_vals > 20) & (dmp > dmn)] = 1.0
            s8[(adx_vals > 20) & (dmn > dmp)] = -1.0
        else:
            s8 = np.zeros(n)
        self.s8 = self.I(lambda: s8, name="S_ADX")

        # Senal 9: ATR expansion + direccion del precio
        atr_vals = ta.atr(high, low, close, length=self.atr_period).fillna(0)
        atr_ma   = atr_vals.rolling(self.vol_window).mean().fillna(0)
        atr_expand = (atr_vals > atr_ma * 1.5).astype(float)
        price_dir  = np.sign(close.diff().fillna(0).values)
        s9 = atr_expand.values * price_dir
        self.s9 = self.I(lambda: s9, name="S_ATR")

        # Senal 10: Volume expansion + direccion del precio
        vol_ma = volume.rolling(self.vol_window).mean().fillna(1)
        vol_ratio = volume / (vol_ma + 1e-8)
        price_dir2 = np.sign(close.diff().fillna(0).values)
        s10 = np.zeros(n)
        s10[vol_ratio > 1.5] = price_dir2[vol_ratio > 1.5]
        self.s10 = self.I(lambda: s10, name="S_VOL")

        # ATR para SL/TP
        atr_sl = ta.atr(high, low, close, length=self.atr_period)
        self.atr = self.I(lambda: atr_sl.values, name="ATR")

        # -- Regime gate (v5): SMA20/50 + ADX --
        sma20_r = ta.sma(close, length=20).fillna(0)
        sma50_r = ta.sma(close, length=50).fillna(0)
        adx_r   = ta.adx(high, low, close, length=14)
        adx_vals_r = adx_r.iloc[:, 0].fillna(0) if adx_r is not None else pd.Series(0, index=close.index)

        raw_regime = np.zeros(n)
        bull_mask = (sma20_r > sma50_r).values & (adx_vals_r > self.regime_adx).values
        bear_mask = (sma20_r < sma50_r).values & (adx_vals_r > self.regime_adx).values
        raw_regime[bull_mask] = 1.0
        raw_regime[bear_mask] = -1.0

        # Estabilidad de régimen: solo confirmar si persiste >= regime_min_bars barras
        # Esto evita el churn por flips rápidos de régimen en 1h
        stable_regime = np.zeros(n)
        min_b = int(self.regime_min_bars)
        for i in range(min_b, n):
            window = raw_regime[i - min_b: i + 1]
            if np.all(window == 1.0):
                stable_regime[i] = 1.0
            elif np.all(window == -1.0):
                stable_regime[i] = -1.0
            else:
                stable_regime[i] = stable_regime[i - 1]  # mantener régimen previo
        self.regime = self.I(lambda: stable_regime, name="Regime")

    def next(self):
        # Minimo de barras para que todos los indicadores esten listos
        if len(self.data) < 55:
            return

        atr   = self.atr[-1]
        price = self.data.Close[-1]

        if np.isnan(atr) or atr <= 0:
            return

        # Desescalar parametros (enteros para optimize)
        sl_m = float(self.sl_mult) / 10.0  # 15 => 1.5
        tp_m = float(self.tp_mult) / 10.0  # 25 => 2.5

        # Suma de 10 senales trend-following
        signals = np.array([
            self.s1[-1], self.s2[-1], self.s3[-1], self.s4[-1], self.s5[-1],
            self.s6[-1], self.s7[-1], self.s8[-1], self.s9[-1], self.s10[-1],
        ])

        if np.any(np.isnan(signals)):
            signals = np.nan_to_num(signals, nan=0.0)

        combined = float(np.sum(signals))
        regime   = float(self.regime[-1])  # +1=BULL, -1=BEAR, 0=SIDEWAYS

        # -- Logica de trading (v5 con regime gate) --
        if self.position:
            # Cerrar si el regimen contradice la posicion
            if self.position.is_long and regime == -1.0:
                self.position.close()
                return
            if self.position.is_short and regime == 1.0:
                self.position.close()
                return
            # Cerrar si el consenso de senales se invierte
            if self.position.is_long and combined <= 0:
                self.position.close()
            elif self.position.is_short and combined >= 0:
                self.position.close()

        else:
            # LONG: solo en regimen BULL con consenso fuerte
            if regime == 1.0 and combined >= self.threshold:
                sl = price - atr * sl_m
                tp = price + atr * tp_m
                if sl < price < tp:
                    self.buy(size=0.95, sl=sl, tp=tp)

            # SHORT: solo en regimen BEAR con consenso negativo fuerte
            elif regime == -1.0 and combined <= -self.threshold:
                sl = price + atr * sl_m
                tp = price - atr * tp_m
                if tp < price < sl:
                    self.sell(size=0.95, sl=sl, tp=tp)


# -- Ejecucion standalone --
if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    print("\n== WeakEnsemble v4 (Trend-Following) -- BTC 1h 365d ==\n")

    df = get_ohlcv("BTC", interval="1h", days=365)
    if df is None or len(df) < 100:
        print("ERROR: Sin datos suficientes")
        sys.exit(1)

    print(f"Datos: {len(df)} barras, {df.index[0]} -> {df.index[-1]}")

    cash = max(10_000, float(df["Close"].max()) * 3)

    bt = Backtest(
        df, WeakEnsemble,
        cash=cash,
        commission=0.001,
        exclusive_orders=True,
        finalize_trades=True,
    )
    stats = bt.run()

    print(stats[["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]",
                 "# Trades", "Win Rate [%]"]])
    print(f"\nProfit Factor: {stats.get('Profit Factor', 'N/A')}")
    print(f"Avg Trade [%]: {stats.get('Avg. Trade [%]', 'N/A')}")

    sharpe = float(stats["Sharpe Ratio"]) if pd.notna(stats["Sharpe Ratio"]) else 0.0
    dd     = float(stats["Max. Drawdown [%]"])
    trades = int(stats["# Trades"])
    wr     = float(stats["Win Rate [%]"]) if pd.notna(stats["Win Rate [%]"]) else 0.0

    print("\nVeredicto:")
    if sharpe >= 1.0 and dd >= -20 and trades >= 30 and wr >= 45:
        print("  APROBADO")
    elif sharpe >= 0.5 and dd >= -35 and trades >= 10:
        print("  PRECAUCION")
    else:
        print("  RECHAZADO")
