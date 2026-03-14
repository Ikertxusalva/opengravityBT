"""
VolatilitySqueezeV4 — Fusión de lo mejor de V1, V2 y V3 + mejoras nuevas.

EVOLUCIÓN:
  V1: Core TTM Squeeze (BB dentro de KC + momentum)       → Sharpe 1.61, 48 trades
  V2: + ADX filter + min_squeeze_bars (precalculado)      → Sharpe 2.10, 21 trades
  V3: + Volume filter + BB 1.8std + KC 1.5mult            → Sharpe 1.45, 31 trades

V4 toma lo mejor de cada versión:
  ✅ V2: squeeze_count precalculado (sin estado mutable, seguro en optimization)
  ✅ V2: ADX threshold 20 (más estricto que V3's 18)
  ✅ V2: SL 2.0x / TP 4.0x ATR (más espacio para respirar que V3's 1.5/3.5)
  ✅ V3: BB std 1.8 (BB más estrecho → squeezes detectados antes)
  ✅ V3: KC mult 1.5 (KC más amplio → solo compresiones reales)
  ✅ V3: Volume filter (vol > vol_mult * vol_MA confirma breakout real)

MEJORAS NUEVAS en V4:
  🆕 DI+ / DI- direction confirmation: solo LONG cuando DI+ > DI- (alcistas dominan)
     solo SHORT cuando DI- > DI+ (bajistas dominan). Elimina entradas contra la fuerza.
  🆕 EMA50 trend filter: solo longs cuando precio > EMA50, solo shorts cuando < EMA50.
     Evita operar contra la tendencia intermedia (el filtro más simple y efectivo).
  🆕 min_squeeze_bars = 3: squeezes más largos = breakouts más potentes y fiables.

ABLATION ESPERADO (basado en V2 documentado):
  - ADX > 20: +93% Sharpe vs sin filtro
  - min_squeeze_bars >= 2: +27% Sharpe vs sin filtro
  - Volume filter (V3): confirma breakouts reales, reduce false positives
  - DI+/DI-: filtra dirección incorrecta sin eliminar trades válidos
  - EMA50: alinea trades con tendencia → reduce shorts en bull markets

PARÁMETROS (mínimo optimizables para evitar overfitting):
  BB: 20/1.8 | KC: 20/1.5 | ADX: 14/20 | MOM: 9
  VOL: window=20, mult=1.3 | EMA: 50 | min_sqz: 3
  SL: 2.0x ATR(14) | TP: 4.0x ATR(14) → ratio 1:2
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy


class VolatilitySqueezeV4(Strategy):
    # ── Bollinger Bands ──────────────────────────────────────────────────────
    bb_len  = 20
    bb_std  = 1.8    # V3: más estrecho → detecta compresión antes que V1/V2

    # ── Keltner Channel ──────────────────────────────────────────────────────
    kc_len  = 20
    kc_mult = 1.5    # V3: más amplio → solo compresiones reales pasan el filtro

    # ── ATR para SL/TP ───────────────────────────────────────────────────────
    atr_len = 14

    # ── ADX (tendencia + dirección) ──────────────────────────────────────────
    adx_len       = 14
    adx_threshold = 20.0  # V2: más estricto que V3's 18

    # ── Momentum ─────────────────────────────────────────────────────────────
    mom_len = 9

    # ── Volume filter (V3) ───────────────────────────────────────────────────
    vol_window = 20
    vol_mult   = 1.3   # El volumen del breakout debe ser > 1.3x la media

    # ── Squeeze duration ─────────────────────────────────────────────────────
    min_squeeze_bars = 3   # V4: más estricto que V2/V3 (2 barras) → breakouts más potentes

    # ── EMA trend filter (NUEVO V4) ──────────────────────────────────────────
    ema_trend_len = 50   # Solo longs sobre EMA50, solo shorts bajo EMA50

    # ── Gestión de riesgo (V2 values: más espacio para respirar) ─────────────
    sl_mult = 2.0   # 2.0x ATR para Stop Loss
    tp_mult = 4.0   # 4.0x ATR para Take Profit → ratio 1:2

    def init(self):
        # ── Series base ──────────────────────────────────────────────────────
        close  = pd.Series(self.data.Close,  index=range(len(self.data.Close)))
        high   = pd.Series(self.data.High,   index=range(len(self.data.High)))
        low    = pd.Series(self.data.Low,    index=range(len(self.data.Low)))
        volume = pd.Series(self.data.Volume, index=range(len(self.data.Volume)))

        # ── Bollinger Bands ──────────────────────────────────────────────────
        bb = ta.bbands(close, length=self.bb_len, std=self.bb_std)
        bb_upper_vals = bb.iloc[:, 2].values  # BBU
        bb_lower_vals = bb.iloc[:, 0].values  # BBL
        self.bb_upper = self.I(lambda: bb_upper_vals, name="BBU")
        self.bb_lower = self.I(lambda: bb_lower_vals, name="BBL")

        # ── Keltner Channel ──────────────────────────────────────────────────
        kc_ema = ta.ema(close, length=self.kc_len)
        kc_atr = ta.atr(high, low, close, length=self.kc_len)
        kc_upper_vals = (kc_ema + self.kc_mult * kc_atr).values
        kc_lower_vals = (kc_ema - self.kc_mult * kc_atr).values
        self.kc_upper = self.I(lambda: kc_upper_vals, name="KCU")
        self.kc_lower = self.I(lambda: kc_lower_vals, name="KCL")

        # ── ATR para SL/TP ───────────────────────────────────────────────────
        atr_vals = ta.atr(high, low, close, length=self.atr_len).values
        self.atr = self.I(lambda: atr_vals, name="ATR")

        # ── Momentum ─────────────────────────────────────────────────────────
        mom_vals = close.diff(self.mom_len).values
        self.momentum = self.I(lambda: mom_vals, name="MOM")

        # ── ADX + DI+/DI- (NUEVO V4) ─────────────────────────────────────────
        # adx() devuelve: [ADX_n, DMP_n (DI+), DMN_n (DI-)]
        adx_df = ta.adx(high, low, close, length=self.adx_len)
        adx_vals = adx_df.iloc[:, 0].values   # ADX
        dip_vals = adx_df.iloc[:, 1].values   # DI+ (directional movement positivo)
        din_vals = adx_df.iloc[:, 2].values   # DI- (directional movement negativo)
        self.adx = self.I(lambda: adx_vals, name="ADX")
        self.dip = self.I(lambda: dip_vals, name="DI+")
        self.din = self.I(lambda: din_vals, name="DI-")

        # ── Volume MA ────────────────────────────────────────────────────────
        vol_ma_vals = ta.sma(volume, length=self.vol_window).values
        self.vol_ma = self.I(lambda: vol_ma_vals, name="VolMA")

        # ── EMA trend filter (NUEVO V4) ──────────────────────────────────────
        ema_trend_vals = ta.ema(close, length=self.ema_trend_len).values
        self.ema_trend = self.I(lambda: ema_trend_vals, name="EMA_TREND")

        # ── Squeeze count PRECALCULADO (V2 approach — sin estado mutable) ────
        # Cuenta barras consecutivas en squeeze para cada posición del array.
        # Esto es más seguro para optimization runs (no hay _squeeze_count mutable).
        squeeze_bool = (
            (bb.iloc[:, 2] < kc_ema + self.kc_mult * kc_atr) &
            (bb.iloc[:, 0] > kc_ema - self.kc_mult * kc_atr)
        ).values

        sqz_count = np.zeros(len(squeeze_bool), dtype=float)
        for i in range(len(squeeze_bool)):
            if squeeze_bool[i]:
                sqz_count[i] = (sqz_count[i - 1] + 1.0) if i > 0 else 1.0
            else:
                sqz_count[i] = 0.0
        self.squeeze_count = self.I(lambda: sqz_count, name="SQZ_CNT")

        # ── Squeeze array (para detectar release: prev=1, now=0) ─────────────
        squeeze_vals = squeeze_bool.astype(float)
        self.squeeze = self.I(lambda: squeeze_vals, name="SQZ")

    def next(self):
        # ── Guard: barras mínimas ─────────────────────────────────────────────
        min_bars = max(self.bb_len, self.kc_len, self.atr_len,
                       self.adx_len, self.mom_len, self.vol_window,
                       self.ema_trend_len) + 5
        if len(self.data) < min_bars:
            return

        # ── Valores actuales ──────────────────────────────────────────────────
        price    = self.data.Close[-1]
        atr      = self.atr[-1]
        mom      = self.momentum[-1]
        adx      = self.adx[-1]
        dip      = self.dip[-1]
        din      = self.din[-1]
        vol      = self.data.Volume[-1]
        vol_ma   = self.vol_ma[-1]
        ema_t    = self.ema_trend[-1]
        sqz_now  = self.squeeze[-1]
        sqz_prev = self.squeeze[-2]
        sqz_cnt  = self.squeeze_count[-2]  # barras en squeeze ANTES del release

        # ── Guard: NaN y valores inválidos ───────────────────────────────────
        if any(np.isnan(x) for x in [atr, mom, adx, dip, din, vol_ma, ema_t]):
            return
        if atr <= 0 or vol_ma <= 0:
            return

        # ── Condición de release del squeeze ─────────────────────────────────
        squeeze_released = (sqz_prev == 1.0) and (sqz_now == 0.0)

        # ── No entrar si ya hay posición o no hay release ─────────────────────
        if self.position or not squeeze_released:
            return

        # ── FILTRO 1: Duración mínima del squeeze ─────────────────────────────
        # Squeezes más largos acumulan más energía → breakouts más potentes
        if sqz_cnt < self.min_squeeze_bars:
            return

        # ── FILTRO 2: ADX confirma tendencia ─────────────────────────────────
        # ADX > 20: hay fuerza direccional real, no es ruido lateral
        if adx < self.adx_threshold:
            return

        # ── FILTRO 3: Volumen confirma el breakout ────────────────────────────
        # El volumen del breakout debe superar la media → participación real
        if vol < self.vol_mult * vol_ma:
            return

        # ── Determinar dirección con momentum + DI+/DI- + EMA trend ──────────
        if mom > 0:
            # Candidato LONG
            # NUEVO V4: DI+ > DI- (alcistas dominan la fuerza direccional)
            if dip <= din:
                return
            # NUEVO V4: precio sobre EMA50 (no operar long en downtrend)
            if price < ema_t:
                return

            sl = price - atr * self.sl_mult
            tp = price + atr * self.tp_mult
            if sl < price < tp:
                self.buy(size=0.95, sl=sl, tp=tp)

        elif mom < 0:
            # Candidato SHORT
            # NUEVO V4: DI- > DI+ (bajistas dominan la fuerza direccional)
            if din <= dip:
                return
            # NUEVO V4: precio bajo EMA50 (no operar short en uptrend)
            if price > ema_t:
                return

            sl = price + atr * self.sl_mult
            tp = price - atr * self.tp_mult
            if tp < price < sl:
                self.sell(size=0.95, sl=sl, tp=tp)


# ── Ejecución standalone ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")

    from moondev.data.data_fetcher import get_ohlcv

    TESTS = [
        ("BTC",  "1h", 365),
        ("ETH",  "1h", 365),
        ("SOL",  "1h", 365),
        ("AVAX", "1h", 365),
        ("BNB",  "1h", 365),
    ]

    print(f"\n{'='*70}")
    print(f"  VolatilitySqueezeV4 — Multi-asset test")
    print(f"{'='*70}")
    print(f"  {'Activo':<8} {'Return':>8} {'Sharpe':>8} {'MaxDD':>8} "
          f"{'Trades':>8} {'WR':>8}")
    print(f"  {'-'*60}")

    for symbol, interval, days in TESTS:
        df = get_ohlcv(symbol, interval=interval, days=days)
        if df is None or len(df) < 200:
            print(f"  {symbol:<8} ERROR: datos insuficientes")
            continue

        cash = max(10_000, float(df["Close"].max()) * 3)
        bt = Backtest(df, VolatilitySqueezeV4, cash=cash, commission=0.001,
                      exclusive_orders=True, finalize_trades=True)
        s = bt.run()

        ret    = float(s["Return [%]"])
        sharpe = float(s["Sharpe Ratio"]) if pd.notna(s["Sharpe Ratio"]) else 0.0
        dd     = float(s["Max. Drawdown [%]"])
        trades = int(s["# Trades"])
        wr     = float(s["Win Rate [%]"]) if pd.notna(s["Win Rate [%]"]) else 0.0

        flag = "✅" if sharpe > 1.0 and dd > -15 and trades >= 15 else \
               "⚠️" if sharpe > 0.5 else "❌"

        print(f"  {flag} {symbol:<6} {ret:>+8.1f}% {sharpe:>8.2f} {dd:>8.1f}% "
              f"{trades:>8} {wr:>7.1f}%")

    print(f"\n  COMPARATIVA HISTÓRICA:")
    print(f"  V1: Sharpe 1.61 | MaxDD -7.4%  | 48 trades | WR 47.9% (BTC 1h)")
    print(f"  V2: Sharpe 2.10 | MaxDD -4.2%  | 21 trades | WR 57.1% (BTC 1h)")
    print(f"  V3: Sharpe 1.45 | MaxDD -4.1%  | 31 trades | WR 54.8% (BTC 1h)")
    print(f"  V4: ???         | ???           | ??? trades | ??? (objetivo: Sharpe >2.0, DD <5%)")
    print(f"{'='*70}\n")
