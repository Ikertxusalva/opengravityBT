#!/usr/bin/env python3
"""
Moon Dev's Backtest AI
Strategy: AtrReversion
This strategy uses ATR and Keltner Channels to spot overextended markets and then enters mean-reversion trades following a 2B price pattern.
Have fun & moon on!
"""

# 1. All necessary imports
import pandas as pd
import numpy as np
from backtesting import Backtest, Strategy

# 2. Strategy class with indicators, entry/exit logic, and risk management

class AtrReversion(Strategy):
    # Configurable parameters (DON'T CHANGE LOGIC or risk settings)
    atr_period = 14
    ema_period = 20
    keltner_mult = 2.0
    risk_percent = 0.01      # 1% risk per trade (of full equity)
    trade_fraction = 0.5     # use half of our normal size for these trades (fraction of equity)

    def init(self):
        # Use self.I() wrapper for indicator calculations
        high = self.data.High
        low = self.data.Low
        close = self.data.Close

        def _atr(high, low, close, period):
            tr = np.maximum(high[1:] - low[1:],
                 np.maximum(np.abs(high[1:] - close[:-1]),
                            np.abs(low[1:]  - close[:-1])))
            tr = np.concatenate([[tr[0]], tr])
            atr = np.full(len(close), np.nan)
            atr[period - 1] = tr[:period].mean()
            for i in range(period, len(close)):
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
            return atr

        def _ema(close, period):
            k = 2.0 / (period + 1)
            ema = np.full(len(close), np.nan)
            ema[period - 1] = close[:period].mean()
            for i in range(period, len(close)):
                ema[i] = close[i] * k + ema[i - 1] * (1 - k)
            return ema

        self.atr = self.I(_atr, high, low, close, self.atr_period)
        self.ema = self.I(_ema, close, self.ema_period)
        # Upper Channel = EMA + keltner_mult * ATR
        # Lower Channel = EMA - keltner_mult * ATR
        self.keltner_upper = self.I(lambda ema, atr: ema + self.keltner_mult * atr, self.ema, self.atr)
        self.keltner_lower = self.I(lambda ema, atr: ema - self.keltner_mult * atr, self.ema, self.atr)

    def next(self):
        # Only proceed if we have enough history
        if len(self.data) < max(self.atr_period, self.ema_period) + 2:
            return

        C = self.data.Close[-1]

        # Only consider new trade entries if we are flat
        if self.position:
            # Exit logic: exit when price reverts back near the EMA midline.
            if self.position.is_short and C < self.ema[-1]:
                self.position.close()
            elif self.position.is_long and C > self.ema[-1]:
                self.position.close()
            return  # Do not open a new trade while in a position

        # ENTRY LOGIC using the previous candle as the reversal candle.
        prev_high = self.data.High[-2]
        prev_low = self.data.Low[-2]
        prev_close = self.data.Close[-2]

        prev_keltner_upper = self.keltner_upper[-2]
        prev_keltner_lower = self.keltner_lower[-2]

        # For Short trade entry: previous candle overextended above upper Keltner + current reversal
        if prev_close > prev_keltner_upper and C < self.ema[-1]:
            order_size = self.trade_fraction
            stop_level = prev_high
            self.sell(size=order_size, sl=stop_level)

        # For Long trade entry: previous candle overextended below lower Keltner + current reversal
        elif prev_close < prev_keltner_lower and C > self.ema[-1]:
            order_size = self.trade_fraction
            stop_level = prev_low
            self.buy(size=order_size, sl=stop_level)


# Example usage:
# if __name__ == '__main__':
#     data = pd.read_csv('your_data.csv', parse_dates=True, index_col='Date')
#     bt = Backtest(data, AtrReversion, cash=100000, commission=.0005)
#     stats = bt.run()
#     print(stats)
#     bt.plot()
