"""
GapAndGoV2 — Deteccion de gaps reales (open vs prev_close) para crypto.

Edge documentado: en el suite de 72 tests (W0gooNe74qs), gap_strategy_long
fue el mejor modelo. En crypto 24/7 los gaps ocurren entre velas cuando hay
news, eventos macro, o volatilidad extrema.

Logica:
  - Gap = (open - prev_close) / prev_close * 100
  - Gap up  > gap_threshold% → LONG (momentum continuation)
  - Gap down < -gap_threshold% → SHORT
  - Filtros: ADX minimo + volumen spike confirman el gap es real
  - SL/TP como % del precio

Adaptacion crypto vs equities:
  - En equities se usa el gap del market open (9:30 ET) vs close anterior
  - En crypto los gaps ocurren entre cualquier vela, no solo al "abrir"
  - Solo señalar gaps con volumen significativo (evitar gaps de baja liquidez)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy
from backtesting.test import SMA
import yfinance as yf


class GapAndGoV2(Strategy):
    gap_threshold = 0.5    # % minimo de gap (open vs prev_close) para señal
    tp_pct = 2.0           # take profit %
    sl_pct = 1.0           # stop loss %
    vol_period = 24        # periodo media de volumen (24 velas 1h = 1 dia)
    vol_min_mult = 1.5     # volumen minimo en el gap = X veces la media
    adx_len = 14
    adx_min = 18.0         # ADX minimo para confirmar tendencia
    atr_len = 14

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high  = pd.Series(self.data.High,  index=range(len(self.data.High)))
        low   = pd.Series(self.data.Low,   index=range(len(self.data.Low)))

        adx_df = ta.adx(high, low, close, length=self.adx_len)
        self.adx = self.I(lambda: adx_df.iloc[:, 0].values, name="ADX")

        atr_vals = ta.atr(high, low, close, length=self.atr_len)
        self.atr = self.I(lambda: atr_vals.values, name="ATR")

        self.vol_avg = self.I(SMA, self.data.Volume, self.vol_period)

    def next(self):
        if len(self.data) < max(self.adx_len, self.vol_period) + 2:
            return

        adx     = self.adx[-1]
        atr     = self.atr[-1]
        vol_avg = self.vol_avg[-1]
        if np.isnan(adx) or np.isnan(atr) or np.isnan(vol_avg) or vol_avg == 0:
            return

        price      = self.data.Close[-1]
        open_px    = self.data.Open[-1]
        prev_close = self.data.Close[-2]
        vol        = self.data.Volume[-1]

        # Gap entre el open de la vela actual y el cierre de la anterior
        gap_pct = (open_px - prev_close) / prev_close * 100

        # Filtro 1: volumen confirma el gap (evita gaps de baja liquidez)
        vol_ok = vol > vol_avg * self.vol_min_mult

        # Filtro 2: ADX confirma que hay tendencia (evita laterales)
        adx_ok = adx > self.adx_min

        if not self.position and vol_ok and adx_ok:
            if gap_pct > self.gap_threshold:
                sl = price * (1 - self.sl_pct / 100)
                tp = price * (1 + self.tp_pct / 100)
                self.buy(sl=sl, tp=tp, size=0.95)

            elif gap_pct < -self.gap_threshold:
                sl = price * (1 + self.sl_pct / 100)
                tp = price * (1 - self.tp_pct / 100)
                self.sell(sl=sl, tp=tp, size=0.95)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")

    combos = [
        ("BTC-USD", "1h", "365d"),
        ("ETH-USD", "1h", "365d"),
        ("SOL-USD", "1h", "365d"),
        ("META",    "1h", "365d"),
        ("NVDA",    "1h", "365d"),
    ]

    print(f"\n=== GapAndGoV2 | gap>={GapAndGoV2.gap_threshold}% | TP={GapAndGoV2.tp_pct}% SL={GapAndGoV2.sl_pct}% ===")
    print(f"{'Symbol':<12} {'Return%':>8} {'Sharpe':>7} {'MaxDD%':>8} {'Trades':>7} {'WR%':>6}  Veredicto")
    print("-" * 62)

    for ticker, interval, period in combos:
        try:
            data = yf.download(ticker, period=period, interval=interval,
                               auto_adjust=True, progress=False)
            data.columns = [c[0] if isinstance(c, tuple) else c for c in data.columns]
            data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()
            if len(data) < 100:
                print(f"{ticker:<12} sin datos suficientes")
                continue

            cash = max(10_000, data["Close"].max() * 3)
            bt = Backtest(data, GapAndGoV2, cash=cash, commission=0.001,
                          exclusive_orders=True, finalize_trades=True)
            s = bt.run()

            sharpe = float(s["Sharpe Ratio"]) if pd.notna(s["Sharpe Ratio"]) else 0.0
            dd     = float(s["Max. Drawdown [%]"])
            trades = int(s["# Trades"])
            wr     = float(s["Win Rate [%]"]) if pd.notna(s["Win Rate [%]"]) else 0.0
            ret    = float(s["Return [%]"])

            verdict = "PASS" if sharpe >= 1.0 and dd > -20 and trades >= 30 and wr >= 45 else "fail"
            print(f"{ticker:<12} {ret:>+8.1f}% {sharpe:>7.2f} {dd:>+8.1f}% {trades:>7} {wr:>5.1f}%  {verdict}")
        except Exception as e:
            print(f"{ticker:<12} ERROR: {e}")
