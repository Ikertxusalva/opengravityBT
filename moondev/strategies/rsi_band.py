"""
RSIBand -- RSI con bandas dinamicas (Pine Script -> Python).

Fuente: moondev tutorial "Tradingview Pinescript to Python Conversion"
Sharpe esperado: 1.03+ (strategy +58% vs BTC -56% en backtest documentado)

v3 -- Mejoras sobre v2:
  - RSI smoothed con EMA(5) para reducir whipsaws en cruces
  - Bandas calculadas con Bollinger del RSI (media +/- 1 std rolling)
    en vez de percentiles (percentiles cambian lento, BB reacciona mejor)
  - Filtro ADX: solo operar cuando ADX > 20 (mercado con tendencia)
  - SL/TP asimetrico: tp_mult=2.5, sl_mult=1.5 (ratio 1:1.67)
  - Solo LONG cuando RSI smoothed cruza encima de upper band
    (breakout alcista = momentum)
  - Solo SHORT cuando RSI smoothed cruza debajo de lower band
    (breakdown bajista = momentum)

Parametros optimizables:
  rsi_period    -- periodo RSI (default 14)
  rsi_smooth    -- periodo EMA del RSI (default 5)
  bb_lookback   -- ventana para Bollinger del RSI (default 50)
  bb_mult       -- multiplicador std para bandas (x10: 10 = 1.0 std)
  sl_mult       -- multiplicador ATR para SL (x10: 15 = 1.5)
  tp_mult       -- multiplicador ATR para TP (x10: 25 = 2.5)
  adx_min       -- ADX minimo para operar (default 20)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class RSIBand(Strategy):
    # -- Parametros optimizables --
    rsi_period  = 14     # Periodo RSI
    rsi_smooth  = 5      # EMA del RSI para suavizar
    bb_lookback = 50     # Ventana rolling para bandas Bollinger del RSI
    bb_mult     = 10     # x10: 10 = 1.0 std desvio para bandas
    sl_mult     = 15     # x10: 15 = 1.5 ATR stop loss
    tp_mult     = 25     # x10: 25 = 2.5 ATR take profit
    adx_min     = 20     # ADX minimo para operar

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high  = pd.Series(self.data.High,  index=range(len(self.data.High)))
        low   = pd.Series(self.data.Low,   index=range(len(self.data.Low)))

        # -- RSI base --
        rsi_raw = ta.rsi(close, length=self.rsi_period).fillna(50)

        # -- RSI smoothed con EMA --
        rsi_ema = ta.ema(rsi_raw, length=self.rsi_smooth).fillna(50)
        self.rsi = self.I(lambda: rsi_ema.values, name="RSI_Smooth")

        # -- Bandas Bollinger sobre el RSI --
        # La media rolling del RSI + std da bandas adaptativas
        rsi_series = pd.Series(rsi_ema.values)
        rsi_ma  = rsi_series.rolling(self.bb_lookback, min_periods=20).mean().fillna(50)
        rsi_std = rsi_series.rolling(self.bb_lookback, min_periods=20).std().fillna(10)

        bb_m = float(self.bb_mult) / 10.0  # 10 => 1.0

        ub_vals = (rsi_ma + rsi_std * bb_m).values
        lb_vals = (rsi_ma - rsi_std * bb_m).values

        self.ub = self.I(lambda: ub_vals, name="UpperBand")
        self.lb = self.I(lambda: lb_vals, name="LowerBand")

        # -- ADX para filtro de tendencia --
        adx_df = ta.adx(high, low, close, length=14)
        if adx_df is not None and adx_df.shape[1] >= 1:
            adx_vals = adx_df.iloc[:, 0].fillna(0).values
        else:
            adx_vals = np.zeros(len(close))
        self.adx = self.I(lambda: adx_vals, name="ADX")

        # -- ATR para SL/TP --
        atr_vals = ta.atr(high, low, close, length=14)
        self.atr = self.I(lambda: atr_vals.values, name="ATR")

    def next(self):
        min_bars = max(self.rsi_period + self.rsi_smooth, self.bb_lookback) + 5
        if len(self.data) < min_bars:
            return

        rsi_now  = self.rsi[-1]
        rsi_prev = self.rsi[-2]
        ub_now   = self.ub[-1]
        ub_prev  = self.ub[-2]
        lb_now   = self.lb[-1]
        lb_prev  = self.lb[-2]
        adx      = self.adx[-1]
        atr      = self.atr[-1]
        price    = self.data.Close[-1]

        if np.isnan(rsi_now) or np.isnan(atr) or atr <= 0:
            return

        # Desescalar parametros
        sl_m = float(self.sl_mult) / 10.0  # 15 => 1.5
        tp_m = float(self.tp_mult) / 10.0  # 25 => 2.5

        # Filtro: solo operar si hay tendencia (ADX > umbral)
        if adx < self.adx_min:
            return

        # -- ENTRY LONG: RSI smoothed cruza por encima de Upper Band --
        # (RSI rompe su rango normal = momentum alcista fuerte)
        cross_above_ub = (rsi_prev <= ub_prev) and (rsi_now > ub_now) and (rsi_now < 85)

        # -- ENTRY SHORT: RSI smoothed cruza por debajo de Lower Band --
        # (RSI rompe su rango normal = momentum bajista fuerte)
        cross_below_lb = (rsi_prev >= lb_prev) and (rsi_now < lb_now) and (rsi_now > 15)

        if not self.position:
            if cross_above_ub:
                # LONG: RSI breakout alcista
                sl = price - atr * sl_m
                tp = price + atr * tp_m
                if sl < price < tp:
                    self.buy(size=0.95, sl=sl, tp=tp)

            elif cross_below_lb:
                # SHORT: RSI breakdown bajista
                sl = price + atr * sl_m
                tp = price - atr * tp_m
                if tp < price < sl:
                    self.sell(size=0.95, sl=sl, tp=tp)

        else:
            # Cierre por senal contraria
            if self.position.is_long and cross_below_lb:
                self.position.close()
            elif self.position.is_short and cross_above_ub:
                self.position.close()


# -- Ejecucion standalone --
if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    print("\n== RSIBand v3 (BB-RSI + ADX) -- BTC 1h 365d ==\n")

    df = get_ohlcv("BTC", interval="1h", days=365)
    if df is None or len(df) < 100:
        print("ERROR: Sin datos suficientes")
        sys.exit(1)

    print(f"Datos: {len(df)} barras, {df.index[0]} -> {df.index[-1]}")

    cash = max(10_000, float(df["Close"].max()) * 3)

    bt = Backtest(
        df, RSIBand,
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
