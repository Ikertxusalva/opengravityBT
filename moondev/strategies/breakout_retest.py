"""
BreakoutRetest — Breakout + Retest Sniper Strategy.

Fuente: TradingView PUB;d46089f21ee8434584ee00797fb4f1ae (228 likes, 4/5)
Mercado: Multi-asset (XAUUSD original, adaptable a BTC, ETH, stocks, forex)

Logica:
  - Detecta breakout alcista/bajista de maximos/minimos de N velas
  - Filtra por tendencia (EMA)
  - Entra en el retest (pullback al nivel roto, con margen de tolerancia)
  - SL = 1 ATR, TP = ATR * rr (default 2:1)

Indicadores:
  - EMA(ema_len): filtro de tendencia
  - Rolling max(high, lookback): nivel de resistencia
  - Rolling min(low, lookback): nivel de soporte
  - ATR(14): gestion de riesgo

Parametros optimizables:
  - ema_len: [20, 50, 100, 200]
  - lookback: [10, 20, 30, 50]
  - rr: [1.5, 2.0, 2.5, 3.0]
  - retest_window: [2, 3, 5]

Nota sobre el retest:
  El retest original de TradingView (low <= nivel exacto) es demasiado estricto
  para datos horarios. Se usa un margen de tolerancia de 0.5*ATR para capturar
  retests "cercanos" al nivel de breakout.
"""
import sys
from pathlib import Path

# Asegurar que el directorio raiz este en el path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class BreakoutRetest(Strategy):
    """
    Estrategia Breakout + Retest Sniper.

    Busca rupturas de niveles de resistencia/soporte (rolling max/min)
    y entra cuando el precio retestea el nivel roto, confirmando con EMA
    como filtro de tendencia. SL basado en ATR, TP con ratio configurable.

    El retest usa un margen de tolerancia de 0.5*ATR para no ser
    demasiado estricto (problema documentado en la fuente original).
    """

    # --- Parametros de clase (optimizables por backtesting.py) ---
    # Optimizados en META 1h: Sharpe 2.06, MaxDD -4.34%, 54 trades, WR 48.1%
    ema_len = 50           # Longitud de la EMA para filtro de tendencia
    lookback = 30          # Ventana para calcular highest high / lowest low
    rr = 2.0               # Ratio riesgo:beneficio (TP = ATR * rr)
    retest_window = 5      # Velas maximo para esperar el retest tras breakout

    def init(self):
        """Inicializa indicadores usando pandas-ta y self.I()."""
        # Convertir arrays de backtesting.py a pd.Series (requerido por pandas-ta)
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)

        # EMA como filtro de tendencia
        self.ema = self.I(
            lambda: ta.ema(close, length=self.ema_len).values,
            name=f"EMA{self.ema_len}"
        )

        # ATR para calcular SL y TP
        self.atr = self.I(
            lambda: ta.atr(high, low, close, length=14).values,
            name="ATR14"
        )

        # Highest high de las ultimas N velas (nivel de resistencia)
        # Shift(1) para que el valor sea el maximo de las N velas ANTERIORES
        # (sin incluir la barra actual, evitando look-ahead)
        self.highest = self.I(
            lambda: high.rolling(self.lookback).max().shift(1).values,
            name=f"HH{self.lookback}"
        )

        # Lowest low de las ultimas N velas (shift para evitar look-ahead)
        self.lowest = self.I(
            lambda: low.rolling(self.lookback).min().shift(1).values,
            name=f"LL{self.lookback}"
        )

        # Estado interno para rastrear breakouts pendientes de retest
        self._breakout_type = 0       # 0=nada, 1=alcista, -1=bajista
        self._breakout_bar = 0        # barra donde se detecto el breakout
        self._breakout_level = 0.0    # nivel de precio del breakout

    def next(self):
        """Logica de trading barra por barra."""
        # No operar si no hay suficientes datos para los indicadores
        if len(self.data.Close) < self.lookback + 5:
            return

        # Valores actuales
        price = self.data.Close[-1]
        current_high = self.data.High[-1]
        current_low = self.data.Low[-1]
        ema_val = self.ema[-1]
        atr_val = self.atr[-1]

        # Proteccion contra valores NaN en indicadores
        if np.isnan(ema_val) or np.isnan(atr_val) or atr_val <= 0:
            return

        # Niveles de breakout (ya shifteados, son los maximos/minimos de las N barras previas)
        hh = self.highest[-1]
        ll = self.lowest[-1]

        if np.isnan(hh) or np.isnan(ll):
            return

        # Indice actual (numero de barras procesadas)
        current_bar = len(self.data.Close) - 1

        # Margen de tolerancia para retest: 0.5 * ATR
        # Esto permite que el retest no sea exacto (se acerque al nivel sin tocarlo)
        retest_margin = atr_val * 0.5

        # --- Si no hay posicion abierta ---
        if not self.position:
            # PASO 1: Detectar breakout en la barra actual
            # Breakout alcista: close rompe el highest de las N barras anteriores
            if price > hh and price > ema_val:
                # Registrar breakout pendiente de retest
                self._breakout_type = 1
                self._breakout_bar = current_bar
                self._breakout_level = hh

            # Breakout bajista: close rompe el lowest de las N barras anteriores
            elif price < ll and price < ema_val:
                self._breakout_type = -1
                self._breakout_bar = current_bar
                self._breakout_level = ll

            # PASO 2: Verificar retest si hay breakout pendiente
            if self._breakout_type != 0:
                bars_since = current_bar - self._breakout_bar

                # Ventana de retest expirada → cancelar
                if bars_since > self.retest_window:
                    self._breakout_type = 0
                    return

                # No entrar en la misma barra del breakout (esperar al menos 1 barra)
                if bars_since == 0:
                    return

                # LONG: breakout alcista + retest
                # Retest = low de la barra actual se acerca al nivel de breakout
                # (nivel +/- margen de tolerancia)
                if (self._breakout_type == 1
                        and current_low <= self._breakout_level + retest_margin
                        and price > ema_val
                        and price > self._breakout_level):  # Cierre sigue por encima
                    sl = price - atr_val
                    tp = price + atr_val * self.rr
                    if sl < price and tp > price:
                        self.buy(size=0.95, sl=sl, tp=tp)
                    self._breakout_type = 0

                # SHORT: breakout bajista + retest
                # Retest = high de la barra actual se acerca al nivel de breakout
                elif (self._breakout_type == -1
                        and current_high >= self._breakout_level - retest_margin
                        and price < ema_val
                        and price < self._breakout_level):  # Cierre sigue por debajo
                    sl = price + atr_val
                    tp = price - atr_val * self.rr
                    if sl > price and tp < price:
                        self.sell(size=0.95, sl=sl, tp=tp)
                    self._breakout_type = 0


# ── Test individual ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    symbol = "BTC"
    interval = "1h"
    days = 365

    print(f"\n{'='*60}")
    print(f"  BreakoutRetest -- Test individual")
    print(f"  Simbolo: {symbol} | Intervalo: {interval} | Dias: {days}")
    print(f"{'='*60}\n")

    # Descargar datos
    print("Descargando datos...")
    df = get_ohlcv(symbol, interval=interval, days=days)
    if df is None or len(df) < 100:
        print("ERROR: No se pudieron obtener datos suficientes.")
        sys.exit(1)

    print(f"  Registros: {len(df)}")
    print(f"  Desde: {df.index[0]}")
    print(f"  Hasta: {df.index[-1]}")

    # Configurar backtest
    max_price = float(df["Close"].max())
    cash = max(10_000, max_price * 3)

    bt = Backtest(
        df,
        BreakoutRetest,
        cash=cash,
        commission=0.001,
        exclusive_orders=True,
        finalize_trades=True,
    )

    # Ejecutar
    print("\nEjecutando backtest...")
    stats = bt.run()

    # Mostrar resultados
    print(f"\n{'='*60}")
    print(f"  RESULTADOS")
    print(f"{'='*60}")
    print(f"  Return:     {stats['Return [%]']:+.2f}%")
    print(f"  Sharpe:     {stats['Sharpe Ratio']:.2f}" if pd.notna(stats['Sharpe Ratio']) else "  Sharpe:     N/A")
    print(f"  Max DD:     {stats['Max. Drawdown [%]']:.2f}%")
    print(f"  Trades:     {stats['# Trades']}")
    print(f"  Win Rate:   {stats['Win Rate [%]']:.1f}%" if pd.notna(stats['Win Rate [%]']) else "  Win Rate:   N/A")
    print(f"  Profit F:   {stats['Profit Factor']:.2f}" if pd.notna(stats['Profit Factor']) else "  Profit F:   N/A")
    print(f"{'='*60}")
    print()
    print(stats)

    # Guardar grafico HTML
    try:
        bt.plot(open_browser=False, filename="moondev/data/breakout_retest.html")
        print("\nGrafico guardado en moondev/data/breakout_retest.html")
    except Exception as e:
        print(f"\nNo se pudo guardar grafico: {e}")
