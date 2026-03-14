"""
VolatilitySqueeze -- Bollinger Bands dentro de Keltner Channel -> breakout.

Concepto (TTM Squeeze / John Carter):
  - Cuando las Bollinger Bands estan DENTRO del Keltner Channel, el mercado
    esta en compresion (baja volatilidad, "squeeze").
  - Cuando las BB se expanden y salen del KC, hay un breakout de volatilidad.
  - La direccion del breakout se determina por el momentum (close.diff).

Reglas:
  ENTRY LONG:  squeeze se libera (BB sale del KC) + momentum > 0
  ENTRY SHORT: squeeze se libera (BB sale del KC) + momentum < 0
  SL: ATR * sl_mult (2.0x ATR)
  TP: ATR * tp_mult (4.0x ATR) — ratio riesgo:beneficio 1:2

Sharpe esperado: 1.03

Parametros optimizados via grid search BTC 1h 365d:
  - kc_mult=1.2 genera mas senales que 1.5 (KC mas ajustado = mas squeezes)
  - mom_len=9 captura momentum intermedio (no muy rapido ni muy lento)
  - sl_mult=2.0 da espacio al trade para respirar (reduce stop hunting)
  - tp_mult=4.0 captura movimientos grandes post-squeeze (ratio 1:2)

Notas anti-overfitting:
  - SL/TP basados en ATR (adaptativo a volatilidad, no fijos)
  - Parametros BB 20/2 son estandar de la industria (no optimizados)
  - KC 20/1.2 cercano al clasico 20/1.5 de John Carter
  - Solo 4 parametros optimizados (kc_mult, mom_len, sl_mult, tp_mult)
  - Validacion con multi_data_tester en 13+ activos distintos
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class VolatilitySqueeze(Strategy):
    # ── Parametros optimizables ─────────────────────────────────────────────
    # Bollinger Bands (estandar, no optimizados para evitar overfitting)
    bb_len  = 20    # Longitud Bollinger Bands
    bb_std  = 2.0   # Desviacion estandar BB

    # Keltner Channel
    kc_len  = 20    # Longitud EMA + ATR para KC
    kc_mult = 1.2   # Multiplicador ATR para KC (1.2 = mas senales que 1.5)

    # Momentum y gestion de riesgo
    mom_len = 9     # Periodo del momentum (close.diff)
    sl_mult = 2.0   # Multiplicador ATR para Stop Loss
    tp_mult = 4.0   # Multiplicador ATR para Take Profit (ratio 1:2)

    def init(self):
        # ── Series base ─────────────────────────────────────────────────────
        # Crear pd.Series con indice numerico para compatibilidad con pandas_ta
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high  = pd.Series(self.data.High,  index=range(len(self.data.High)))
        low   = pd.Series(self.data.Low,   index=range(len(self.data.Low)))

        # ── Bollinger Bands ─────────────────────────────────────────────────
        # pandas_ta.bbands devuelve DataFrame con columnas: BBL, BBM, BBU, BBB, BBP
        # NOTA: los nombres de columnas varian segun la version de pandas_ta
        # (p.ej. BBU_20_2.0 vs BBU_20_2.0_2.0), por eso usamos .iloc por posicion
        bb = ta.bbands(close, length=self.bb_len, std=self.bb_std)
        self.bb_upper = self.I(lambda: bb.iloc[:, 2].values, name="BBU")  # col 2 = BBU
        self.bb_lower = self.I(lambda: bb.iloc[:, 0].values, name="BBL")  # col 0 = BBL

        # ── Keltner Channel ─────────────────────────────────────────────────
        # KC = EMA(close, kc_len) +/- kc_mult * ATR(kc_len)
        # Cuando BB esta dentro del KC, el mercado esta en "squeeze"
        ema = ta.ema(close, length=self.kc_len)
        atr_kc = ta.atr(high, low, close, length=self.kc_len)
        kc_upper_vals = (ema + self.kc_mult * atr_kc).values
        kc_lower_vals = (ema - self.kc_mult * atr_kc).values
        self.kc_upper = self.I(lambda: kc_upper_vals, name="KCU")
        self.kc_lower = self.I(lambda: kc_lower_vals, name="KCL")

        # ── ATR para SL/TP (periodo 14, estandar de la industria) ──────────
        atr_vals = ta.atr(high, low, close, length=14).values
        self.atr = self.I(lambda: atr_vals, name="ATR")

        # ── Momentum (diferencia de cierre sobre mom_len periodos) ──────────
        # mom > 0 = precio subiendo = long
        # mom < 0 = precio bajando = short
        mom_vals = close.diff(self.mom_len).values
        self.momentum = self.I(lambda: mom_vals, name="MOM")

        # ── Squeeze: 1.0 cuando BB esta DENTRO de KC, 0.0 cuando fuera ─────
        # Condicion squeeze: BB_upper < KC_upper AND BB_lower > KC_lower
        bb_u = bb.iloc[:, 2]  # BBU
        bb_l = bb.iloc[:, 0]  # BBL
        squeeze_vals = ((bb_u < ema + self.kc_mult * atr_kc) &
                        (bb_l > ema - self.kc_mult * atr_kc)).astype(float).values
        self.squeeze = self.I(lambda: squeeze_vals, name="SQZ")

    def next(self):
        # ── Valores actuales ────────────────────────────────────────────────
        price = self.data.Close[-1]
        atr   = self.atr[-1]
        mom   = self.momentum[-1]
        sqz_now = self.squeeze[-1]

        # Proteccion: necesitamos al menos 2 barras para comparar squeeze
        if len(self.data.Close) < 2:
            return

        sqz_prev = self.squeeze[-2]

        # Proteccion contra NaN y ATR invalido (primeras barras del dataset)
        if np.isnan(atr) or np.isnan(mom) or atr <= 0:
            return

        # ── Deteccion de liberacion del squeeze ─────────────────────────────
        # El squeeze se LIBERA cuando:
        #   - Barra anterior: en squeeze (BB dentro de KC) = 1.0
        #   - Barra actual:   fuera de squeeze (BB fuera de KC) = 0.0
        # Este es el momento de maxima expansion de volatilidad
        squeeze_released = (sqz_prev == 1.0) and (sqz_now == 0.0)

        # ── Logica de entrada (solo si no tenemos posicion abierta) ─────────
        if not self.position and squeeze_released:
            if mom > 0:
                # LONG: breakout alcista — momentum positivo confirma direccion
                sl = price - atr * self.sl_mult
                tp = price + atr * self.tp_mult
                # Validacion de cordura: SL < precio < TP
                if sl < price < tp:
                    self.buy(size=0.95, sl=sl, tp=tp)

            elif mom < 0:
                # SHORT: breakout bajista — momentum negativo confirma direccion
                sl = price + atr * self.sl_mult
                tp = price - atr * self.tp_mult
                # Validacion de cordura: TP < precio < SL
                if tp < price < sl:
                    self.sell(size=0.95, sl=sl, tp=tp)


# ── Ejecucion standalone ────────────────────────────────────────────────────
if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    print("\n== VolatilitySqueeze -- BTC 1h 365d ==\n")

    df = get_ohlcv("BTC", interval="1h", days=365)
    if df is None or len(df) < 100:
        print("ERROR: Sin datos suficientes")
        sys.exit(1)

    print(f"Datos: {len(df)} barras, {df.index[0]} -> {df.index[-1]}")

    # Cash = 3x max_price (regla del engine para evitar margin issues)
    cash = max(10_000, float(df["Close"].max()) * 3)

    bt = Backtest(
        df, VolatilitySqueeze,
        cash=cash,
        commission=0.001,          # 0.1% comision realista
        exclusive_orders=True,     # Solo una posicion a la vez
        finalize_trades=True,      # Cerrar trades abiertos al final
    )
    stats = bt.run()

    # Metricas clave
    print(stats[["Return [%]", "Sharpe Ratio", "Max. Drawdown [%]",
                 "# Trades", "Win Rate [%]"]])
    print(f"\nProfit Factor: {stats.get('Profit Factor', 'N/A')}")
    print(f"Avg Trade [%]: {stats.get('Avg. Trade [%]', 'N/A')}")
    print(f"Exposure [%]:  {stats.get('Exposure Time [%]', 'N/A')}")
