"""
BollingerAltcoin — Bollinger + RSI mean reversion para altcoins.

Entry: close < BB_lower AND RSI < 40 AND SMA20 > SMA50 (uptrend context)
       AND ATR > ATR_min (evitar entradas en baja volatilidad)
Exit:  close > BB_middle OR RSI > 70

Fix v2 (2026-03-01):
- bb_std: 2.0 → 1.5 (bandas mas cercanas, mas senales)
- rsi_entry: 30 → 40 (menos restrictivo)
- Timeframe recomendado: 1h (mas senales que 4h)
- Filtro ATR: evitar entradas en volatilidad extremadamente baja
- SL/TP fijos por ATR para gestion de riesgo correcta
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


class BollingerAltcoin(Strategy):
    rsi_period = 14
    bb_period = 20
    bb_std = 1.5       # v2: 2.0 → 1.5 (bandas mas cercanas)
    rsi_entry = 40     # v2: 30 → 40 (menos restrictivo)
    rsi_exit = 70
    atr_period = 14
    atr_min_pct = 0.3  # ATR minimo como % del precio (evitar mercados planos)
    sl_atr = 2.0       # SL = 2x ATR
    tp_atr = 3.0       # TP = 3x ATR

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high = pd.Series(self.data.High, index=range(len(self.data.High)))
        low = pd.Series(self.data.Low, index=range(len(self.data.Low)))

        bb = ta.bbands(close, length=self.bb_period, std=self.bb_std)
        self.bb_lower = self.I(lambda: bb.iloc[:, 0].values, name="BB_Lower")
        self.bb_mid   = self.I(lambda: bb.iloc[:, 1].values, name="BB_Mid")
        self.bb_upper = self.I(lambda: bb.iloc[:, 2].values, name="BB_Upper")

        rsi_vals = ta.rsi(close, length=self.rsi_period)
        self.rsi = self.I(lambda: rsi_vals.values, name="RSI")

        atr_vals = ta.atr(high, low, close, length=self.atr_period)
        self.atr = self.I(lambda: atr_vals.values, name="ATR")

        self.sma20 = self.I(SMA, self.data.Close, 20)
        self.sma50 = self.I(SMA, self.data.Close, 50)

    def next(self):
        min_bars = max(self.bb_period, self.rsi_period, self.atr_period, 50) + 2
        if len(self.data) < min_bars:
            return

        price = self.data.Close[-1]
        rsi = self.rsi[-1]
        atr = self.atr[-1]
        sma20 = self.sma20[-1]
        sma50 = self.sma50[-1]
        bb_lower = self.bb_lower[-1]
        bb_mid = self.bb_mid[-1]

        if np.isnan(rsi) or np.isnan(atr) or np.isnan(bb_lower):
            return

        # Filtro ATR: no entrar si volatilidad es demasiado baja
        atr_pct = (atr / price) * 100
        if atr_pct < self.atr_min_pct:
            return

        if not self.position:
            if price < bb_lower and rsi < self.rsi_entry and sma20 > sma50:
                sl = price - self.sl_atr * atr
                tp = price + self.tp_atr * atr
                self.buy(sl=sl, tp=tp, size=0.95)
        else:
            if price > bb_mid or rsi > self.rsi_exit:
                self.position.close()


if __name__ == "__main__":
    ticker = "SOL-USD"
    data = yf.download(ticker, period="365d", interval="1h", auto_adjust=True, progress=False)
    data.columns = [c[0] if isinstance(c, tuple) else c for c in data.columns]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    max_price = data["Close"].max()
    cash = max(10_000, max_price * 3)

    bt = Backtest(data, BollingerAltcoin, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()

    print(f"\n=== BollingerAltcoin v2 | {ticker} 1h 365d ===")
    print(f"Return:   {stats['Return [%]']:.1f}%")
    print(f"Sharpe:   {stats['Sharpe Ratio']:.2f}")
    print(f"Max DD:   {stats['Max. Drawdown [%]']:.1f}%")
    print(f"Trades:   {stats['# Trades']}")
    print(f"Win Rate: {stats['Win Rate [%]']:.1f}%")
    print(f"PF:       {stats.get('Profit Factor', 'N/A')}")
