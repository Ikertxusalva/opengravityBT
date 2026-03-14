"""
GapAndGo -- Momentum continuation trading entre barras.
Fuente: moondev 72-test suite (Sharpe 1.03, Sortino 3.32)

v4 -- rediseno total para crypto 24/7:
  En crypto no hay gaps reales (Open vs prevClose < 0.04% tipicamente).
  En vez de buscar gaps, detectamos IMPULSOS FUERTES: barras cuyo cuerpo
  (Close - Open) excede un umbral basado en ATR. Entramos a favor del impulso
  esperando continuacion en la siguiente barra.

  Logica:
    body = Close[i] - Open[i]
    body_pct = body / ATR  (normalizado por volatilidad)
    Si body_pct > impulse_threshold => LONG (impulso alcista fuerte)
    Si body_pct < -impulse_threshold => SHORT (impulso bajista fuerte)

  Filtros:
    - RSI no extremo (evita entrar en sobrecompra/sobreventa)
    - EMA(50) como filtro de tendencia (solo long si precio > EMA50)
    - ATR-based SL/TP

Parametros optimizables:
  impulse_mult  -- umbral de impulso en multiplos de ATR (1.5 = barra > 1.5x ATR)
  sl_mult       -- multiplicador ATR para SL
  tp_mult       -- multiplicador ATR para TP
  rsi_filter    -- umbral RSI (no comprar si RSI > 100-rsi_filter)
  ema_trend     -- periodo EMA para filtro de tendencia
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class GapAndGo(Strategy):
    # Parametros optimizables
    impulse_mult = 15     # x10: 15 = 1.5x ATR como umbral de impulso
    sl_mult      = 15     # x10: 15 = 1.5x ATR para stop loss
    tp_mult      = 30     # x10: 30 = 3.0x ATR para take profit
    rsi_filter   = 30     # RSI: no comprar si RSI > (100-rsi_filter)
    ema_trend    = 50     # Periodo EMA para filtro de tendencia

    def init(self):
        # Convertir a pd.Series para pandas-ta
        close  = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high   = pd.Series(self.data.High,  index=range(len(self.data.High)))
        low    = pd.Series(self.data.Low,   index=range(len(self.data.Low)))
        open_  = pd.Series(self.data.Open,  index=range(len(self.data.Open)))

        # ATR(14) para normalizar impulsos y para SL/TP
        atr_vals = ta.atr(high, low, close, length=14)
        self.atr = self.I(lambda: atr_vals.values, name="ATR")

        # Cuerpo de la barra normalizado por ATR (impulso)
        body = close - open_
        body_ratio = (body / (atr_vals + 1e-8)).fillna(0).values
        self.body_ratio = self.I(lambda: body_ratio, name="BodyRatio")

        # RSI(14) para filtrar extremos
        rsi_vals = ta.rsi(close, length=14).fillna(50).values
        self.rsi = self.I(lambda: rsi_vals, name="RSI")

        # EMA para filtro de tendencia
        ema_vals = ta.ema(close, length=self.ema_trend).fillna(0).values
        self.ema = self.I(lambda: ema_vals, name="EMA_Trend")

    def next(self):
        # Esperar suficientes barras
        if len(self.data) < self.ema_trend + 5:
            return

        price      = self.data.Close[-1]
        atr        = self.atr[-1]
        body_ratio = self.body_ratio[-1]
        rsi        = self.rsi[-1]
        ema_val    = self.ema[-1]

        # Validacion de datos
        if np.isnan(atr) or np.isnan(body_ratio) or np.isnan(rsi) or atr <= 0:
            return

        # Desescalar parametros (enteros para optimize)
        impulse_th = float(self.impulse_mult) / 10.0  # 15 => 1.5
        sl_m       = float(self.sl_mult) / 10.0       # 15 => 1.5
        tp_m       = float(self.tp_mult) / 10.0       # 30 => 3.0

        # Detectar impulso fuerte
        impulse_up   = body_ratio > impulse_th
        impulse_down = body_ratio < -impulse_th

        if not self.position:
            if impulse_up and rsi < (100 - self.rsi_filter) and price > ema_val:
                # Impulso alcista + RSI no sobrecomprado + tendencia alcista => LONG
                sl = price - atr * sl_m
                tp = price + atr * tp_m
                if sl < price < tp:
                    self.buy(size=0.95, sl=sl, tp=tp)

            elif impulse_down and rsi > self.rsi_filter and price < ema_val:
                # Impulso bajista + RSI no sobrevendido + tendencia bajista => SHORT
                sl = price + atr * sl_m
                tp = price - atr * tp_m
                if tp < price < sl:
                    self.sell(size=0.95, sl=sl, tp=tp)


# -- Ejecucion standalone --
if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    print("\n== GapAndGo (Impulse Momentum) -- BTC 1h 365d ==\n")

    df = get_ohlcv("BTC", interval="1h", days=365)
    if df is None or len(df) < 100:
        print("Sin datos suficientes para backtest")
        sys.exit(1)

    print(f"Datos: {len(df)} barras, {df.index[0]} -> {df.index[-1]}")

    cash = max(10_000, float(df["Close"].max()) * 3)

    bt = Backtest(df, GapAndGo, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
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
