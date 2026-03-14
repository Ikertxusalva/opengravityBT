"""
SuperTrendAdaptive -- Estrategia de seguimiento de tendencia basada en SuperTrend.

Fuente: TradingView PUB;179278b0ad6d41c496515eff282fd6b3 (228 likes, 5/5 estrellas)
Tipo: Trend Following -- SuperTrend flip

Logica:
    Entry Long:  SuperTrend direction pasa de -1 a +1 (flip alcista)
    Entry Short: SuperTrend direction pasa de +1 a -1 (flip bajista)
    SL: basado en ATR * sl_atr_mult
    TP: basado en ATR * tp_atr_mult
    R:R = 2:1

Indicadores:
    - SuperTrend(ATR length, factor) via pandas-ta -- senal principal
    - ATR(length) -- para SL y TP dinamicos

Parametros optimizables:
    - atr_length: [7, 10, 14, 20]
    - factor: [2.0, 2.5, 3.0, 3.5, 4.0]
    - sl_atr_mult: [1.0, 1.5, 2.0]
    - tp_atr_mult: [2.0, 3.0, 4.0]
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


def _compute_supertrend_dir(high, low, close, length, multiplier):
    """
    Calcula la direccion del SuperTrend usando pandas-ta nativo.

    pandas-ta.supertrend() retorna DataFrame con 4 columnas:
        iloc[:, 0] = SUPERT_L_M    (precio del supertrend)
        iloc[:, 1] = SUPERTd_L_M   (direccion: 1=alcista, -1=bajista)
        iloc[:, 2] = SUPERTl_L_M   (linea inferior - solo en alcista)
        iloc[:, 3] = SUPERTs_L_M   (linea superior - solo en bajista)

    Usamos iloc para evitar problemas con nombres de columna dinamicos.

    Retorna:
        np.ndarray con 1.0 (alcista) o -1.0 (bajista) para cada barra.
        Las primeras 'length' barras seran NaN, se rellenan con 1.0.
    """
    st = ta.supertrend(high, low, close, length=int(length), multiplier=float(multiplier))
    if st is None or st.empty:
        return np.ones(len(close))

    # Columna de direccion es la segunda (iloc[:, 1])
    direction = st.iloc[:, 1].values.copy()

    # Rellenar NaN iniciales con 0 (sin senal)
    direction = np.nan_to_num(direction, nan=0.0)

    return direction


def _compute_atr(high, low, close, length):
    """
    Calcula ATR usando pandas-ta.

    Retorna:
        np.ndarray con valores ATR. NaN iniciales rellenados con 0.
    """
    atr = ta.atr(high, low, close, length=int(length))
    if atr is None:
        return np.zeros(len(close))
    result = atr.values.copy()
    result = np.nan_to_num(result, nan=0.0)
    return result


class SuperTrendAdaptive(Strategy):
    """
    Estrategia SuperTrend Adaptive -- Trend Following.

    Entra cuando el SuperTrend hace flip de direccion.
    SL y TP basados en ATR para adaptarse a la volatilidad.
    """
    # Parametros optimizables
    atr_length = 10       # Periodo ATR para SuperTrend y SL/TP
    factor = 3.0          # Multiplicador SuperTrend
    sl_atr_mult = 1.5     # Multiplicador ATR para Stop Loss
    tp_atr_mult = 3.0     # Multiplicador ATR para Take Profit

    def init(self):
        # Convertir a pd.Series (requerido por pandas-ta)
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)

        # Indicador SuperTrend direction: 1=alcista, -1=bajista
        # Usa pandas-ta nativo, accediendo a columnas por posicion (iloc)
        self.st_dir = self.I(
            _compute_supertrend_dir,
            high, low, close,
            self.atr_length, self.factor,
            name='STdir'
        )

        # ATR para calculo de SL y TP dinamicos
        self.atr = self.I(
            _compute_atr,
            high, low, close,
            self.atr_length,
            name='ATR'
        )

    def next(self):
        # Necesitamos al menos 2 barras validas de SuperTrend para detectar flip
        if len(self.data) < self.atr_length + 2:
            return

        # Valores actuales
        price = self.data.Close[-1]
        atr_val = self.atr[-1]
        st_now = self.st_dir[-1]
        st_prev = self.st_dir[-2]

        # Verificar que ATR es valido (no NaN ni cero)
        if atr_val <= 0:
            return

        # Verificar que SuperTrend tiene senal valida (no 0 = NaN rellenado)
        if st_now == 0 or st_prev == 0:
            return

        # --- Logica de entrada ---
        if not self.position:
            # LONG: flip de bajista (-1) a alcista (+1)
            if st_prev == -1 and st_now == 1:
                sl = price - atr_val * self.sl_atr_mult
                tp = price + atr_val * self.tp_atr_mult
                self.buy(size=0.95, sl=sl, tp=tp)

            # SHORT: flip de alcista (+1) a bajista (-1)
            elif st_prev == 1 and st_now == -1:
                sl = price + atr_val * self.sl_atr_mult
                tp = price - atr_val * self.tp_atr_mult
                self.sell(size=0.95, sl=sl, tp=tp)


# -- Main: test rapido con BTC-USD 1h 1y -----------------------------------------------
if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    symbol = "BTC"
    interval = "1h"
    days = 365

    print(f"\n--- SuperTrendAdaptive ---")
    print(f"Descargando {symbol} ({interval}, {days}d)...")

    df = get_ohlcv(symbol, interval=interval, days=days)
    if df is None or len(df) < 50:
        print("ERROR: no se pudo obtener datos.")
        sys.exit(1)

    print(f"Registros: {len(df)}")
    print(f"Desde: {df.index[0]}")
    print(f"Hasta: {df.index[-1]}")

    # Cash: auto-escala 3x max_price (regla del engine)
    max_price = float(df["Close"].max())
    cash = max(10_000, max_price * 3)

    bt = Backtest(
        df, SuperTrendAdaptive,
        cash=cash,
        commission=0.001,
        exclusive_orders=True,
        finalize_trades=True,
    )
    stats = bt.run()
    print(f"\n{stats}")
    print(f"\nTrades: {stats['# Trades']}")
    print(f"Return: {stats['Return [%]']:.2f}%")
    print(f"Sharpe: {stats['Sharpe Ratio']:.2f}" if pd.notna(stats['Sharpe Ratio']) else "Sharpe: N/A")
    print(f"Max DD: {stats['Max. Drawdown [%]']:.2f}%")
    print(f"Win Rate: {stats['Win Rate [%]']:.1f}%" if pd.notna(stats['Win Rate [%]']) else "Win Rate: N/A")
