"""
FundingReversal — reversal en extremos de funding rate.

Entry: BTC en uptrend (SMA20 > SMA50) como proxy de "funding negativo en uptrend"
       usando RSI < 35 como proxy de funding extremo negativo (sin datos reales)
Exit:  RSI > 55 o SL 2%

Nota: sin histórico de funding rates, simulamos el edge con RSI en uptrend context.
Inspirado en: funding_agent de moon-dev-ai-agents
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy
from backtesting.test import SMA
import yfinance as yf


class FundingReversal(Strategy):
    rsi_oversold = 35
    rsi_exit = 55
    sl_pct = 0.02     # 2% stop loss

    def init(self):
        close = pd.Series(self.data.Close)
        self.rsi = self.I(lambda: ta.rsi(close, 14).values)
        self.sma20 = self.I(SMA, self.data.Close, 20)
        self.sma50 = self.I(SMA, self.data.Close, 50)

    def next(self):
        if not self.position:
            uptrend = self.sma20[-1] > self.sma50[-1]
            oversold = self.rsi[-1] < self.rsi_oversold
            if uptrend and oversold:
                entry = self.data.Close[-1]
                sl = entry * (1 - self.sl_pct)
                self.buy(size=0.95, sl=sl)
        else:
            if self.rsi[-1] > self.rsi_exit:
                self.position.close()


if __name__ == "__main__":
    data = yf.download("BTC-USD", period="365d", interval="1h", auto_adjust=True)
    data.columns = ["Close", "High", "Low", "Open", "Volume"]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    bt = Backtest(data, FundingReversal, cash=10_000, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()
    print(stats)
