"""
TechnicalPatterns — patrones de price action: engulfing + MACD crossover.

Entry: Bullish Engulfing detectado Y MACD histogram positivo
Exit:  Bearish Engulfing O MACD histogram negativo

Inspirado en: listingarb_agent de moon-dev-ai-agents
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import pandas_ta as ta
import numpy as np
from backtesting import Backtest, Strategy
import yfinance as yf


def bullish_engulfing(opens, closes):
    """True si la vela actual envuelve completamente la anterior (alcista)."""
    prev_bear = closes[-2] < opens[-2]
    curr_bull = closes[-1] > opens[-1]
    curr_engulfs = opens[-1] < closes[-2] and closes[-1] > opens[-2]
    return prev_bear and curr_bull and curr_engulfs


def bearish_engulfing(opens, closes):
    """True si la vela actual envuelve completamente la anterior (bajista)."""
    prev_bull = closes[-2] > opens[-2]
    curr_bear = closes[-1] < opens[-1]
    curr_engulfs = opens[-1] > closes[-2] and closes[-1] < opens[-2]
    return prev_bull and curr_bear and curr_engulfs


class TechnicalPatterns(Strategy):
    def init(self):
        close = pd.Series(self.data.Close)
        macd_df = ta.macd(close)
        self.macd_hist = self.I(lambda: macd_df.iloc[:, 2].values)

    def next(self):
        if len(self.data) < 3:
            return

        opens = self.data.Open
        closes = self.data.Close
        hist = self.macd_hist[-1]

        if not self.position:
            if bullish_engulfing(opens, closes) and hist > 0:
                self.buy(size=0.95)
        else:
            if bearish_engulfing(opens, closes) or hist < 0:
                self.position.close()


if __name__ == "__main__":
    data = yf.download("ETH-USD", period="365d", interval="4h", auto_adjust=True)
    data.columns = ["Close", "High", "Low", "Open", "Volume"]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    bt = Backtest(data, TechnicalPatterns, cash=10_000, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()
    print(stats)
