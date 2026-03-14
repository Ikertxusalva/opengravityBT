"""
ORBStrategy -- Opening Range Breakout.
Sharpe documentado: 2.81 en stocks (catalogo moondev).

Logica:
  - Define el "Opening Range" como el maximo/minimo de las primeras N barras
    (proxy con rolling window, ya que datos intradiarios no siempre marcan sesion)
  - Breakout alcista: precio cierra por encima del ORB High + filtro EMA tendencia
  - Breakout bajista: precio cierra por debajo del ORB Low + filtro EMA tendencia
  - SL/TP dimensionados con ATR(14) y multiplicadores configurables
  - Sin posicion abierta => busca nueva entrada
  - Posicion gestionada por SL/TP automaticos de backtesting.py

Parametros optimizados (grid search SPY 1h 1y, 600 combinaciones):
  - orb_bars = 6  (barras del Opening Range)
  - sl_mult  = 1.5 (multiplicador ATR para stop loss)
  - tp_mult  = 5.0 (multiplicador ATR para take profit — RR 1:3.3)
  - ema_len  = 30  (EMA rapida para filtro de tendencia)

Nota: el Sharpe de 2.81 se refiere al catalogo moondev en condiciones
especificas. Con datos yfinance y backtesting.py, los resultados varian.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class ORBStrategy(Strategy):
    # Parametros optimizados via grid search (SPY 1h 1y, 600 combos)
    orb_bars = 6    # Barras del Opening Range (max/min rolling)
    sl_mult  = 1.5  # Multiplicador ATR para stop loss
    tp_mult  = 5.0  # Multiplicador ATR para take profit (RR ~1:3.3)
    ema_len  = 30   # Longitud EMA para filtro de tendencia

    def init(self):
        # Series de precio como pd.Series para pandas-ta
        close = pd.Series(self.data.Close)
        high  = pd.Series(self.data.High)
        low   = pd.Series(self.data.Low)

        # ATR(14) para dimensionar SL/TP de forma adaptativa a la volatilidad
        self.atr = self.I(
            lambda: ta.atr(high, low, close, length=14).values,
            name="ATR"
        )

        # EMA de tendencia: solo operamos breakouts a favor de la tendencia
        self.ema = self.I(
            lambda: ta.ema(close, length=self.ema_len).values,
            name="EMA"
        )

        # Opening Range High: maximo de las N barras anteriores (shifted para evitar look-ahead)
        # shift(1) asegura que el rango se calcula con barras YA cerradas
        self.orb_high = self.I(
            lambda: high.rolling(self.orb_bars).max().shift(1).values,
            name="ORB_H"
        )

        # Opening Range Low: minimo de las N barras anteriores (shifted)
        self.orb_low = self.I(
            lambda: low.rolling(self.orb_bars).min().shift(1).values,
            name="ORB_L"
        )

    def next(self):
        price = self.data.Close[-1]
        atr   = self.atr[-1]
        ema   = self.ema[-1]
        orb_h = self.orb_high[-1]
        orb_l = self.orb_low[-1]

        # Validacion de datos: evitar NaN y valores invalidos
        if np.isnan(atr) or np.isnan(ema) or np.isnan(orb_h) or np.isnan(orb_l) or atr <= 0:
            return

        if not self.position:
            # ── BREAKOUT ALCISTA ──
            # Precio supera el ORB High Y esta por encima de la EMA (tendencia alcista)
            if price > orb_h and price > ema:
                sl = price - atr * self.sl_mult  # Stop loss debajo del precio
                tp = price + atr * self.tp_mult  # Take profit por encima
                # Validar coherencia: SL < precio < TP
                if sl < price < tp:
                    self.buy(size=0.95, sl=sl, tp=tp)

            # ── BREAKOUT BAJISTA ──
            # Precio rompe el ORB Low Y esta por debajo de la EMA (tendencia bajista)
            elif price < orb_l and price < ema:
                sl = price + atr * self.sl_mult  # Stop loss encima del precio
                tp = price - atr * self.tp_mult  # Take profit por debajo
                # Validar coherencia: TP < precio < SL
                if tp < price < sl:
                    self.sell(size=0.95, sl=sl, tp=tp)


# ── Ejecucion standalone ────────────────────────────────────────────────────────
if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    # Descargar datos SPY 1h (1 ano) — stock ideal para ORB
    df = get_ohlcv("SPY", interval="1h", days=365)
    if df is None or len(df) < 100:
        print("Sin datos suficientes para backtest")
        sys.exit(1)

    # Auto-escalar cash: 3x precio maximo para evitar margin calls
    cash = max(10_000, float(df["Close"].max()) * 3)

    bt = Backtest(df, ORBStrategy, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()

    # Mostrar metricas principales
    print("\n=== ORBStrategy -- SPY 1h 1y ===")
    print(stats[["Return [%]", "Sharpe Ratio", "Sortino Ratio",
                 "Max. Drawdown [%]", "# Trades", "Win Rate [%]",
                 "Profit Factor", "Avg. Trade [%]"]])
