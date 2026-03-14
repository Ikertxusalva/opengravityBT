"""
LiquidationDip -- Rebote post-liquidacion.
La estrategia mas mencionada en moondev (11,843 veces en 228 videos).

Proxy: volumen extremo + caida fuerte de precio --> comprar el bounce.

Logica:
  1. Volumen de la barra > N veces la media movil de volumen (proxy de cascada de liquidaciones)
  2. Caida porcentual Open->Close supera umbral minimo (drop_pct)
  3. RSI en zona de sobreventa (confirma agotamiento vendedor)
  4. Entrada con SL/TP basados en ATR

Parametros optimizables:
  vol_mult      -- multiplicador de volumen vs media (default 3.0)
  drop_pct      -- % minimo de caida en la barra (default 2.0)
  rsi_threshold -- umbral RSI oversold (default 35)
  sl_mult       -- multiplicador ATR para stop loss (default 2.0)
  tp_mult       -- multiplicador ATR para take profit (default 3.0)
  vol_window    -- ventana para la media movil de volumen (default 20)
"""
import sys
from pathlib import Path

# Asegurar que el directorio raiz del proyecto este en el path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class LiquidationDip(Strategy):
    """
    Estrategia de rebote post-liquidacion.

    Detecta barras con volumen extremo combinado con caida fuerte
    de precio (proxy de cascada de liquidaciones en futuros/perps).
    Compra el bounce esperando reversion a la media.
    """

    # -- Parametros optimizables --
    vol_mult      = 3.0   # Volumen debe ser N veces la media
    drop_pct      = 2.0   # % de caida minima en la barra (Open -> Close)
    rsi_threshold = 35    # RSI por debajo de este nivel = oversold
    sl_mult       = 2.0   # Multiplicador ATR para stop loss
    tp_mult       = 3.0   # Multiplicador ATR para take profit
    vol_window    = 20    # Ventana para calcular la media de volumen

    def init(self):
        """
        Pre-calcula indicadores usando pandas_ta.
        Todos los indicadores se envuelven en self.I() para que
        backtesting.py los alinee correctamente con los datos.
        """
        close  = pd.Series(self.data.Close)
        high   = pd.Series(self.data.High)
        low    = pd.Series(self.data.Low)
        volume = pd.Series(self.data.Volume)

        # RSI de 14 periodos -- mide agotamiento del momentum vendedor
        self.rsi = self.I(
            lambda: ta.rsi(close, length=14).values,
            name="RSI"
        )

        # ATR de 14 periodos -- para dimensionar SL/TP en terminos de volatilidad
        self.atr = self.I(
            lambda: ta.atr(high, low, close, length=14).values,
            name="ATR"
        )

        # Media movil simple de volumen -- baseline para detectar volumen anomalo
        self.vol_ma = self.I(
            lambda: volume.rolling(self.vol_window).mean().values,
            name="VolMA"
        )

    def next(self):
        """
        Logica de trading bar-a-bar.

        Condiciones de entrada (TODAS deben cumplirse):
          1. Sin posicion abierta (no duplicar)
          2. Volumen actual > vol_mult * media de volumen
          3. Caida porcentual (open - close) / open > drop_pct / 100
          4. RSI < rsi_threshold (zona oversold)
          5. SL y TP validos (SL < precio < TP)
        """
        price  = self.data.Close[-1]
        open_  = self.data.Open[-1]
        volume = self.data.Volume[-1]
        rsi    = self.rsi[-1]
        atr    = self.atr[-1]
        vol_ma = self.vol_ma[-1]

        # Validacion de NaN y valores invalidos -- evita errores en barras iniciales
        if np.isnan(rsi) or np.isnan(atr) or np.isnan(vol_ma):
            return
        if atr <= 0 or vol_ma <= 0:
            return

        # -- Condicion 1: Volumen extremo --
        # Un spike de volumen indica que se estan ejecutando muchas liquidaciones
        # en cascada (margin calls, stop hunts, etc.)
        high_volume = volume > self.vol_mult * vol_ma

        # -- Condicion 2: Caida fuerte de precio --
        # La barra debe mostrar una caida significativa (open > close)
        # Esto filtra barras de alto volumen que no son de panico vendedor
        strong_drop = (open_ - price) / open_ > self.drop_pct / 100

        # -- Condicion 3: RSI en zona oversold --
        # Confirma que el activo esta sobrevendido y listo para un bounce
        oversold = rsi < self.rsi_threshold

        # -- Entrada --
        if not self.position:
            if high_volume and strong_drop and oversold:
                # SL basado en ATR (por debajo del precio actual)
                sl = price - atr * self.sl_mult
                # TP basado en ATR (por encima del precio actual)
                tp = price + atr * self.tp_mult

                # Validar que SL y TP son coherentes
                if sl < price < tp:
                    # Comprar con 95% del capital disponible
                    self.buy(size=0.95, sl=sl, tp=tp)


# ── Ejecucion individual ─────────────────────────────────────────────────────
if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    print("\n" + "=" * 60)
    print("  LiquidationDip -- Backtest Individual BTC 1h 365d")
    print("=" * 60)

    # Descargar datos de BTC (HyperLiquid via data_fetcher)
    print("\nDescargando datos BTC 1h...")
    df = get_ohlcv("BTC", interval="1h", days=365)
    if df is None or len(df) < 100:
        print("ERROR: Sin datos suficientes para BTC")
        sys.exit(1)

    print(f"Datos: {len(df)} barras desde {df.index[0]} hasta {df.index[-1]}")

    # Cash escalado al precio maximo (regla del engine: 3x max_price)
    cash = max(10_000, float(df["Close"].max()) * 3)
    print(f"Cash inicial: ${cash:,.0f}")

    # Ejecutar backtest
    bt = Backtest(
        df,
        LiquidationDip,
        cash=cash,
        commission=0.001,           # 0.1% comision (maker/taker promedio)
        exclusive_orders=True,      # Una sola posicion a la vez
        finalize_trades=True,       # Cerrar trades abiertos al final
    )
    stats = bt.run()

    # Mostrar metricas clave
    print("\n" + "-" * 40)
    print("RESULTADOS:")
    print("-" * 40)
    print(stats[[
        "Return [%]",
        "Sharpe Ratio",
        "Max. Drawdown [%]",
        "# Trades",
        "Win Rate [%]",
    ]])
    print("-" * 40)

    # Veredicto rapido
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
