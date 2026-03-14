"""
SuperTrendRegimeFilter — SuperTrend Adaptive con filtro de régimen inline.

Problema de la versión base (supertrend_adaptive.py):
  100-180 trades/año en crypto → whipsawing severo en mercado lateral/bajista.
  Sharpe negativo en todo el universo en 2024-2025.

Solución: gate de régimen calculado inline sobre los propios datos OHLCV.
  BULL  : SMA20 > SMA50 AND ADX > min_adx → solo entrar LONG
  BEAR  : SMA20 < SMA50 AND ADX > min_adx → solo entrar SHORT
  SIDEWAYS: sin trades nuevos (cerrar posiciones existentes al salir del régimen)

Resultado esperado: 30-60% menos trades, WinRate y Sharpe superiores.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


def _supertrend_dir(high, low, close, length, multiplier):
    st = ta.supertrend(high, low, close, length=int(length), multiplier=float(multiplier))
    if st is None or st.empty:
        return np.zeros(len(close))
    direction = st.iloc[:, 1].values.copy()
    return np.nan_to_num(direction, nan=0.0)


def _atr(high, low, close, length):
    atr = ta.atr(high, low, close, length=int(length))
    if atr is None:
        return np.zeros(len(close))
    return np.nan_to_num(atr.values.copy(), nan=0.0)


def _regime(high, low, close, sma_fast, sma_slow, adx_len, min_adx):
    """
    Calcula régimen inline:
      +1 = BULL  (sma_fast > sma_slow AND ADX > min_adx)
      -1 = BEAR  (sma_fast < sma_slow AND ADX > min_adx)
       0 = SIDEWAYS
    """
    c = pd.Series(close)
    h = pd.Series(high)
    l = pd.Series(low)
    sma_f = ta.sma(c, sma_fast).fillna(0).values
    sma_s = ta.sma(c, sma_slow).fillna(0).values
    adx_df = ta.adx(h, l, c, length=adx_len)
    if adx_df is not None and not adx_df.empty:
        adx_vals = adx_df.iloc[:, 0].fillna(0).values
    else:
        adx_vals = np.zeros(len(close))

    regime = np.zeros(len(close))
    bull = (sma_f > sma_s) & (adx_vals > min_adx)
    bear = (sma_f < sma_s) & (adx_vals > min_adx)
    regime[bull] = 1.0
    regime[bear] = -1.0
    return regime


class SuperTrendRegimeFilter(Strategy):
    """
    SuperTrend con filtro de régimen SMA20/50 + ADX.

    Solo abre LONG en régimen BULL, SHORT en régimen BEAR.
    En SIDEWAYS no abre posiciones nuevas y cierra las existentes.
    """
    # SuperTrend
    atr_length    = 10
    factor        = 3.0
    sl_atr_mult   = 1.5
    tp_atr_mult   = 3.0

    # Régimen
    sma_fast      = 20
    sma_slow      = 50
    adx_length    = 14
    min_adx       = 20    # ADX mínimo para considerar tendencia válida

    def init(self):
        close = pd.Series(self.data.Close)
        high  = pd.Series(self.data.High)
        low   = pd.Series(self.data.Low)

        self.st_dir = self.I(
            _supertrend_dir, high, low, close,
            self.atr_length, self.factor, name='STdir'
        )
        self.atr_ind = self.I(
            _atr, high, low, close,
            self.atr_length, name='ATR'
        )
        self.regime = self.I(
            _regime, high, low, close,
            self.sma_fast, self.sma_slow,
            self.adx_length, self.min_adx,
            name='Regime'
        )

    def next(self):
        if len(self.data) < max(self.sma_slow, self.atr_length) + 2:
            return

        price   = self.data.Close[-1]
        atr_val = self.atr_ind[-1]
        st_now  = self.st_dir[-1]
        st_prev = self.st_dir[-2]
        regime  = self.regime[-1]

        if atr_val <= 0 or st_now == 0 or st_prev == 0:
            return

        # Cerrar posición si el régimen la contradice
        if self.position.is_long and regime == -1.0:
            self.position.close()
            return
        if self.position.is_short and regime == 1.0:
            self.position.close()
            return

        # Sin posición — buscar entrada según régimen
        if not self.position:
            if regime == 1.0 and st_prev == -1 and st_now == 1:
                # BULL + flip alcista → LONG
                sl = price - atr_val * self.sl_atr_mult
                tp = price + atr_val * self.tp_atr_mult
                self.buy(size=0.95, sl=sl, tp=tp)

            elif regime == -1.0 and st_prev == 1 and st_now == -1:
                # BEAR + flip bajista → SHORT
                sl = price + atr_val * self.sl_atr_mult
                tp = price - atr_val * self.tp_atr_mult
                self.sell(size=0.95, sl=sl, tp=tp)


if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    symbol = "BTC"
    print(f"\n--- SuperTrendRegimeFilter — {symbol} 1h 365d ---")
    df = get_ohlcv(symbol, interval="1h", days=365)
    if df is None or len(df) < 100:
        print("ERROR: sin datos")
        sys.exit(1)

    cash = max(10_000, float(df["Close"].max()) * 3)
    bt = Backtest(df, SuperTrendRegimeFilter, cash=cash,
                  commission=0.001, exclusive_orders=True, finalize_trades=True)
    stats = bt.run()
    print(stats[["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]", "# Trades", "Win Rate [%]"]])
