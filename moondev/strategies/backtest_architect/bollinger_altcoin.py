"""
BollingerAltcoin — Bollinger + RSI mean reversion para altcoins.

Entry: close < BB_lower AND RSI < 30 AND SMA20 > SMA50 (uptrend context)
Exit:  close > BB_middle OR RSI > 70

Inspirado en: listingarb_agent de moon-dev-ai-agents

STATUS: LABORATORIO — señal muy esporádica (<=4 trades en la mayoría de activos).
Necesita: bajar bb_std, relajar RSI threshold, o cambiar timeframe.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy
from backtesting.test import SMA
import yfinance as yf


class BollingerAltcoin(Strategy):
    rsi_period = 14
    bb_period = 20
    bb_std = 2.0

    def init(self):
        close = pd.Series(self.data.Close)
        bb = ta.bbands(close, length=self.bb_period, std=self.bb_std)
        self.bb_lower = self.I(lambda: bb.iloc[:, 0].values)
        self.bb_mid = self.I(lambda: bb.iloc[:, 1].values)
        self.bb_upper = self.I(lambda: bb.iloc[:, 2].values)
        self.rsi = self.I(ta.rsi, close, self.rsi_period)
        self.sma20 = self.I(SMA, self.data.Close, 20)
        self.sma50 = self.I(SMA, self.data.Close, 50)

    def next(self):
        price = self.data.Close[-1]
        rsi = self.rsi[-1]
        sma20 = self.sma20[-1]
        sma50 = self.sma50[-1]
        bb_lower = self.bb_lower[-1]
        bb_mid = self.bb_mid[-1]

        if not self.position:
            if price < bb_lower and rsi < 30 and sma20 > sma50:
                self.buy(size=0.95)
        else:
            if price > bb_mid or rsi > 70:
                self.position.close()


if __name__ == "__main__":
    data = yf.download("SOL-USD", period="180d", interval="4h", auto_adjust=True)
    data.columns = ["Close", "High", "Low", "Open", "Volume"]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    bt = Backtest(data, BollingerAltcoin, cash=10_000, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()
    print(stats)
    bt.plot(open_browser=False, filename="moondev/data/bollinger_altcoin.html")
