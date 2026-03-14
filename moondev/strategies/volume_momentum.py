"""
VolumeMomentum — Volume Spike Reversal en 4h timeframe.

Logica: cuando hay un volumen extremo (spike) en una vela, el movimiento
tiende a agotarse. Operar en contra del movimiento tras el spike.

Entry LONG (reversal bajista):
  - Volumen > vol_multiplier * media
  - Precio bajo X% en lookback velas (caida extrema)
  - RSI en zona de sobreventa (<40)

Entry SHORT (reversal alcista):
  - Volumen > vol_multiplier * media
  - Precio subio X% en lookback velas (subida extrema)
  - RSI en zona de sobrecompra (>65)

Exit: SL/TP por ATR

Fix v3 (2026-03-01):
- Timeframe 4h (menos ruido que 1h)
- Contrarian: operar en contra del spike de volumen
- RSI como confirmacion de agotamiento
- vol_avg_period: 42 velas (7d en 4h)

Inspirado en: new_or_top_agent de moon-dev-ai-agents
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


class VolumeMomentum(Strategy):
    rsi_overbought = 65    # RSI para señal SHORT contrarian
    rsi_oversold = 40      # RSI para señal LONG contrarian
    vol_multiplier = 2.0   # spike de volumen: X veces la media
    price_change_min = 3   # % cambio en lookback_bars para confirmar el movimiento extremo
    vol_avg_period = 42    # media de volumen: 7 dias en 4h
    lookback_bars = 3      # velas para calcular el price_change (3 * 4h = 12h)
    atr_period = 14
    sl_atr = 1.5           # SL = 1.5x ATR
    tp_atr = 3.0           # TP = 3.0x ATR (RR = 2:1)

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high = pd.Series(self.data.High, index=range(len(self.data.High)))
        low = pd.Series(self.data.Low, index=range(len(self.data.Low)))

        rsi_vals = ta.rsi(close, 14)
        self.rsi = self.I(lambda: rsi_vals.values, name="RSI")

        atr_vals = ta.atr(high, low, close, length=self.atr_period)
        self.atr = self.I(lambda: atr_vals.values, name="ATR")

        self.vol_avg = self.I(SMA, self.data.Volume, self.vol_avg_period)

    def next(self):
        min_bars = max(self.vol_avg_period, self.atr_period, 14) + self.lookback_bars + 2
        if len(self.data) < min_bars:
            return

        rsi = self.rsi[-1]
        atr = self.atr[-1]
        vol = self.data.Volume[-1]
        vol_avg = self.vol_avg[-1]

        if np.isnan(rsi) or np.isnan(atr) or np.isnan(vol_avg) or vol_avg == 0:
            return

        price_now = self.data.Close[-1]
        price_ago = self.data.Close[-self.lookback_bars]
        price_change = (price_now - price_ago) / price_ago * 100
        vol_spike = vol > vol_avg * self.vol_multiplier

        if not self.position:
            # LONG contrarian: caida extrema con volumen spike + RSI oversold
            if (vol_spike
                    and price_change < -self.price_change_min
                    and rsi < self.rsi_oversold):
                sl = price_now - self.sl_atr * atr
                tp = price_now + self.tp_atr * atr
                self.buy(sl=sl, tp=tp, size=0.95)

            # SHORT contrarian: subida extrema con volumen spike + RSI overbought
            elif (vol_spike
                    and price_change > self.price_change_min
                    and rsi > self.rsi_overbought):
                sl = price_now + self.sl_atr * atr
                tp = price_now - self.tp_atr * atr
                self.sell(sl=sl, tp=tp, size=0.95)


if __name__ == "__main__":
    ticker = "BTC-USD"
    # 4h es el timeframe optimo para esta estrategia
    data = yf.download(ticker, period="2y", interval="4h", auto_adjust=True, progress=False)
    data.columns = [c[0] if isinstance(c, tuple) else c for c in data.columns]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    max_price = data["Close"].max()
    cash = max(10_000, max_price * 3)

    bt = Backtest(data, VolumeMomentum, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()

    print(f"\n=== VolumeMomentum v3 | {ticker} 4h 2y ===")
    print(f"Return:   {stats['Return [%]']:.1f}%")
    print(f"Sharpe:   {stats['Sharpe Ratio']:.2f}")
    print(f"Max DD:   {stats['Max. Drawdown [%]']:.1f}%")
    print(f"Trades:   {stats['# Trades']}")
    print(f"Win Rate: {stats['Win Rate [%]']:.1f}%")
    pf = stats.get('Profit Factor', 'N/A')
    print(f"PF:       {pf if pf == 'N/A' else f'{pf:.2f}'}")
    print(f"\nTambien en 1h 365d:")

    data1h = yf.download(ticker, period="365d", interval="1h", auto_adjust=True, progress=False)
    data1h.columns = [c[0] if isinstance(c, tuple) else c for c in data1h.columns]
    data1h = data1h[["Open", "High", "Low", "Close", "Volume"]].dropna()

    bt1h = Backtest(data1h, VolumeMomentum, cash=cash, commission=0.001,
                    exclusive_orders=True, finalize_trades=True)
    stats1h = bt1h.run(vol_avg_period=24, lookback_bars=4, price_change_min=2)
    print(f"Return: {stats1h['Return [%]']:.1f}%  Sharpe: {stats1h['Sharpe Ratio']:.2f}  "
          f"DD: {stats1h['Max. Drawdown [%]']:.1f}%  Trades: {stats1h['# Trades']}  "
          f"WR: {stats1h['Win Rate [%]']:.1f}%")
