"""
VolumeMomentum — contrarian reversal en top gainers con volumen extremo.

Entry: RSI > 70 AND volume_24h > 2× avg_7d AND price_change > 15%
       (apuesta a reversión tras run extremo)
Exit:  RSI < 50 OR volumen cae 50% vs entrada

Inspirado en: new_or_top_agent de moon-dev-ai-agents

STATUS: LABORATORIO — Diseño casi inactivo; 0-3 trades en la mayoría de activos.
Condiciones demasiado restrictivas; rediseñar señales o cambiar timeframe.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy
from backtesting.test import SMA
import yfinance as yf


class VolumeMomentum(Strategy):
    rsi_overbought = 70
    rsi_exit = 50
    vol_multiplier = 2.0   # volumen actual vs media 7d
    price_change_min = 15  # % subida mínima en 24h
    vol_avg_period = 42    # 7d en 4h = 42 velas

    def init(self):
        close = pd.Series(self.data.Close)
        self.rsi = self.I(lambda: ta.rsi(close, 14).values)
        self.vol_avg = self.I(SMA, self.data.Volume, self.vol_avg_period)
        self._entry_volume = 0.0

    def next(self):
        if len(self.data) < self.vol_avg_period + 6:
            return

        rsi = self.rsi[-1]
        vol = self.data.Volume[-1]
        vol_avg = self.vol_avg[-1]
        price_now = self.data.Close[-1]
        price_24h_ago = self.data.Close[-6]
        price_change = (price_now - price_24h_ago) / price_24h_ago * 100

        if not self.position:
            if (rsi > self.rsi_overbought
                    and vol > vol_avg * self.vol_multiplier
                    and price_change > self.price_change_min):
                self.sell(size=0.95)  # short: apuesta a reversión
                self._entry_volume = vol
        else:
            vol_dropped = vol < self._entry_volume * 0.5 if self._entry_volume else False
            if rsi < self.rsi_exit or vol_dropped:
                self.position.close()


if __name__ == "__main__":
    data = yf.download("BTC-USD", period="365d", interval="4h", auto_adjust=True)
    data.columns = ["Close", "High", "Low", "Open", "Volume"]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    bt = Backtest(data, VolumeMomentum, cash=10_000, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    stats = bt.run()
    print(stats)
