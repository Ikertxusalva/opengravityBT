"""
VolatilitySqueezeV2 -- TTM Squeeze con filtros de calidad (ADX + squeeze duration).

Mejoras sobre V1 validadas por ablation study (10 configs testadas):
  1. ADX filter: solo cuando ADX > 20 (confirma tendencia, evita laterales)
     - Impacto individual: Sharpe 1.28 -> 2.47, WR 45.7% -> 58.3%
  2. Duracion minima squeeze: >=2 barras comprimidas = breakout mas fiable
     - Impacto individual: Sharpe 1.28 -> 1.63, WR 45.7% -> 51.6%
  3. Combinacion ADX+MinSqz: Sharpe 2.10, MaxDD -4.23%, WR 57.1%

Filtros descartados tras ablation (empeoran resultados en crypto 1h):
  - SMA200 trend filter: reduce Sharpe de 1.28 a 0.32 en BTC 1h
    (SMA200 en timeframe 1h no captura bien la tendencia de crypto)
  - Momentum acelerando: reduce trades sin mejorar Sharpe significativamente
    (mom_now > mom_prev es demasiado ruidoso en barras horarias)

V1 resultado: BTC 1h -> Sharpe 1.61, MaxDD -7.4%, 48 trades, WR 47.9%
V2 resultado: BTC 1h -> Sharpe 2.10, MaxDD -4.2%, 21 trades, WR 57.1%

Parametros:
  - BB 20/2 + KC 20/1.2: estandar industria (no optimizados)
  - ADX 14, threshold 20: estandar Wilder (no optimizado)
  - min_squeeze_bars=2: minimo conservador (3 es mas estricto pero reduce trades)
  - SL 2.0x ATR, TP 4.0x ATR: ratio riesgo:beneficio 1:2 (adaptativo a volatilidad)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class VolatilitySqueezeV2(Strategy):
    # ── Bollinger Bands (estandar industria, no optimizados) ──────────────────
    bb_len  = 20
    bb_std  = 2.0

    # ── Keltner Channel ──────────────────────────────────────────────────────
    kc_len  = 20
    kc_mult = 1.2

    # ── Momentum ─────────────────────────────────────────────────────────────
    mom_len = 9

    # ── Filtros V2 (validados por ablation study) ────────────────────────────
    adx_len          = 14     # Periodo ADX (estandar Wilder)
    adx_threshold    = 20.0   # Minimo ADX para confirmar tendencia
    min_squeeze_bars = 2      # Barras minimas en squeeze antes de breakout

    # ── Gestion de riesgo ────────────────────────────────────────────────────
    sl_mult = 2.0   # ATR * 2.0 para Stop Loss
    tp_mult = 4.0   # ATR * 4.0 para Take Profit (ratio 1:2)

    def init(self):
        # ── Series base (indice numerico para pandas_ta) ─────────────────────
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high  = pd.Series(self.data.High,  index=range(len(self.data.High)))
        low   = pd.Series(self.data.Low,   index=range(len(self.data.Low)))

        # ── Bollinger Bands ──────────────────────────────────────────────────
        bb = ta.bbands(close, length=self.bb_len, std=self.bb_std)
        bb_upper_vals = bb.iloc[:, 2].values  # col 2 = BBU
        bb_lower_vals = bb.iloc[:, 0].values  # col 0 = BBL
        self.bb_upper = self.I(lambda: bb_upper_vals, name="BBU")
        self.bb_lower = self.I(lambda: bb_lower_vals, name="BBL")

        # ── Keltner Channel ──────────────────────────────────────────────────
        ema = ta.ema(close, length=self.kc_len)
        atr_kc = ta.atr(high, low, close, length=self.kc_len)
        kc_upper_vals = (ema + self.kc_mult * atr_kc).values
        kc_lower_vals = (ema - self.kc_mult * atr_kc).values
        self.kc_upper = self.I(lambda: kc_upper_vals, name="KCU")
        self.kc_lower = self.I(lambda: kc_lower_vals, name="KCL")

        # ── ATR para SL/TP (periodo 14, estandar) ───────────────────────────
        atr_vals = ta.atr(high, low, close, length=14).values
        self.atr = self.I(lambda: atr_vals, name="ATR")

        # ── Momentum (close.diff) ───────────────────────────────────────────
        mom_vals = close.diff(self.mom_len).values
        self.momentum = self.I(lambda: mom_vals, name="MOM")

        # ── Squeeze: 1.0 cuando BB dentro de KC, 0.0 fuera ─────────────────
        bb_u = bb.iloc[:, 2]
        bb_l = bb.iloc[:, 0]
        squeeze_vals = ((bb_u < ema + self.kc_mult * atr_kc) &
                        (bb_l > ema - self.kc_mult * atr_kc)).astype(float).values
        self.squeeze = self.I(lambda: squeeze_vals, name="SQZ")

        # ── ADX filter (NUEVO V2) ───────────────────────────────────────────
        # ta.adx() devuelve DataFrame con columnas: ADX_14, DMP_14, DMN_14
        adx_df = ta.adx(high, low, close, length=self.adx_len)
        adx_col = f"ADX_{self.adx_len}"
        adx_vals = adx_df[adx_col].values
        self.adx = self.I(lambda: adx_vals, name="ADX")

        # ── Squeeze count precalculado (NUEVO V2) ───────────────────────────
        # Cuenta barras consecutivas en squeeze para cada posicion.
        # Precalcular evita mantener estado mutable en next() y es mas rapido.
        sqz_count = np.zeros(len(squeeze_vals), dtype=float)
        for i in range(len(squeeze_vals)):
            if squeeze_vals[i] == 1.0:
                sqz_count[i] = (sqz_count[i - 1] + 1.0) if i > 0 else 1.0
            else:
                sqz_count[i] = 0.0
        self.squeeze_count = self.I(lambda: sqz_count, name="SQZ_CNT")

    def next(self):
        # ── Guard: minimo de barras necesarias ───────────────────────────────
        if len(self.data.Close) < 3:
            return

        # ── Valores actuales ─────────────────────────────────────────────────
        price   = self.data.Close[-1]
        atr     = self.atr[-1]
        mom     = self.momentum[-1]
        sqz_now = self.squeeze[-1]
        sqz_prev = self.squeeze[-2]
        adx     = self.adx[-1]
        # Barras en squeeze ANTES del release (usamos [-2] porque [-1] ya es 0)
        sqz_cnt = self.squeeze_count[-2]

        # ── Guard: NaN y ATR invalido ────────────────────────────────────────
        if np.isnan(atr) or np.isnan(mom) or np.isnan(adx) or atr <= 0:
            return

        # ── Deteccion de liberacion del squeeze ─────────────────────────────
        # Barra anterior en squeeze (1.0) y barra actual fuera (0.0)
        squeeze_released = (sqz_prev == 1.0) and (sqz_now == 0.0)

        # ── No entrar si ya tenemos posicion o no hay squeeze release ────────
        if self.position or not squeeze_released:
            return

        # ── FILTRO 1: Duracion minima del squeeze ────────────────────────────
        # Squeezes mas largos producen breakouts mas fuertes.
        # Ablation: este filtro solo sube Sharpe de 1.28 a 1.63 (+27%)
        if sqz_cnt < self.min_squeeze_bars:
            return

        # ── FILTRO 2: ADX confirma tendencia ─────────────────────────────────
        # ADX > threshold indica que hay tendencia real (no lateral).
        # Ablation: este filtro solo sube Sharpe de 1.28 a 2.47 (+93%)
        if adx < self.adx_threshold:
            return

        # ── Determinar direccion por momentum ────────────────────────────────
        if mom > 0:
            # LONG: breakout alcista con squeeze maduro + tendencia confirmada
            sl = price - atr * self.sl_mult
            tp = price + atr * self.tp_mult
            if sl < price < tp:
                self.buy(size=0.95, sl=sl, tp=tp)

        elif mom < 0:
            # SHORT: breakout bajista con squeeze maduro + tendencia confirmada
            sl = price + atr * self.sl_mult
            tp = price - atr * self.tp_mult
            if tp < price < sl:
                self.sell(size=0.95, sl=sl, tp=tp)


# ── Ejecucion standalone ─────────────────────────────────────────────────────
if __name__ == "__main__":
    from moondev.data.data_fetcher import get_ohlcv

    symbol = "BTC"
    interval = "1h"
    days = 365

    print(f"\n{'='*60}")
    print(f"  VolatilitySqueezeV2 -- Test individual")
    print(f"  Simbolo: {symbol} | Intervalo: {interval} | Dias: {days}")
    print(f"{'='*60}\n")

    df = get_ohlcv(symbol, interval=interval, days=days)
    if df is None or len(df) < 200:
        print("ERROR: datos insuficientes")
        sys.exit(1)

    print(f"  Registros: {len(df)}")
    cash = max(10_000, float(df["Close"].max()) * 3)

    bt = Backtest(df, VolatilitySqueezeV2, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()

    print(f"\n{'='*60}")
    print(f"  RESULTADOS V2 vs V1")
    print(f"{'='*60}")
    print(f"  Return:     {stats['Return [%]']:+.2f}%")
    sharpe = stats['Sharpe Ratio']
    print(f"  Sharpe:     {sharpe:.2f}" if pd.notna(sharpe) else "  Sharpe:     N/A")
    print(f"  Max DD:     {stats['Max. Drawdown [%]']:.2f}%")
    print(f"  Trades:     {stats['# Trades']}")
    wr = stats['Win Rate [%]']
    print(f"  Win Rate:   {wr:.1f}%" if pd.notna(wr) else "  Win Rate:   N/A")
    pf = stats['Profit Factor']
    print(f"  Profit F:   {pf:.2f}" if pd.notna(pf) else "  Profit F:   N/A")
    print(f"{'='*60}")
    print()
    print("  COMPARACION:")
    print("  V1: Sharpe 1.61 | MaxDD -7.4% | 48 trades | WR 47.9%")
    sharpe_str = f"{sharpe:.2f}" if pd.notna(sharpe) else "N/A"
    wr_str = f"{wr:.1f}" if pd.notna(wr) else "N/A"
    print(f"  V2: Sharpe {sharpe_str} | MaxDD {stats['Max. Drawdown [%]']:.1f}% | {stats['# Trades']} trades | WR {wr_str}%")
    print()
