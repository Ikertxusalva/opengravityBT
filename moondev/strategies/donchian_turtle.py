"""
Estrategia: DonchianTurtleBreakout
Tipo: Trend Following / Breakout
Logica: Sistema Turtle clasico adaptado.
  - 20-period Donchian Channel (highest high, lowest low)
  - LONG: close rompe por encima del high de 20 periodos
  - SHORT: close rompe por debajo del low de 20 periodos
  - Trail stop con canal de 10 periodos (exit channel)
  - SL: 2x ATR(10), TP: 3x ATR(10) como backup
  - Size: 0.95 del capital
Fuente: ideas.txt #20
"""
import pandas as pd
import numpy as np
import pandas_ta as ta
from backtesting import Strategy, Backtest


class DonchianTurtleBreakout(Strategy):
    entry_length = 20     # Donchian entry channel
    exit_length = 10      # Donchian exit channel (trailing)
    atr_length = 10
    sl_atr_mult = 2.0
    tp_atr_mult = 3.0

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high = pd.Series(self.data.High, index=range(len(self.data.High)))
        low = pd.Series(self.data.Low, index=range(len(self.data.Low)))

        # Entry channel: 20-period highest high / lowest low
        dc_upper = high.rolling(self.entry_length).max()
        dc_lower = low.rolling(self.entry_length).min()
        self.dc_upper = self.I(lambda: dc_upper.values, name="DC_Upper")
        self.dc_lower = self.I(lambda: dc_lower.values, name="DC_Lower")

        # Exit channel: 10-period (for trailing stops)
        exit_upper = high.rolling(self.exit_length).max()
        exit_lower = low.rolling(self.exit_length).min()
        self.exit_upper = self.I(lambda: exit_upper.values, name="Exit_Upper")
        self.exit_lower = self.I(lambda: exit_lower.values, name="Exit_Lower")

        # ATR
        atr_vals = ta.atr(high, low, close, length=self.atr_length)
        self.atr = self.I(lambda: atr_vals.values, name="ATR")

    def next(self):
        if len(self.data) < self.entry_length + 5:
            return

        price = self.data.Close[-1]
        price_prev = self.data.Close[-2]
        dc_u = self.dc_upper[-2]   # Previous bar's channel (avoid look-ahead)
        dc_l = self.dc_lower[-2]
        exit_u = self.exit_upper[-2]
        exit_l = self.exit_lower[-2]
        atr = self.atr[-1]

        if any(np.isnan(x) for x in [dc_u, dc_l, exit_u, exit_l, atr]):
            return
        if atr <= 0:
            return

        # Exit logic first (trailing with exit channel)
        if self.position:
            if self.position.is_long and price < exit_l:
                self.position.close()
                return
            elif self.position.is_short and price > exit_u:
                self.position.close()
                return

        # Entry logic
        if not self.position:
            sl = atr * self.sl_atr_mult
            tp = atr * self.tp_atr_mult

            # Breakout above 20-period high
            if price > dc_u and price_prev <= dc_u:
                self.buy(sl=price - sl, tp=price + tp)
            # Breakout below 20-period low
            elif price < dc_l and price_prev >= dc_l:
                self.sell(sl=price + sl, tp=price - tp)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf

    data = yf.download("BTC-USD", period="1y", interval="1h", auto_adjust=True, progress=False)
    data.columns = [c[0] if isinstance(c, tuple) else c for c in data.columns]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    cash = max(10_000, data["Close"].max() * 3)
    bt = Backtest(data, DonchianTurtleBreakout, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    s = bt.run()
    print(f"Return: {float(s['Return [%]']):.1f}%  "
          f"Sharpe: {float(s['Sharpe Ratio']) if str(s['Sharpe Ratio']) != 'nan' else 0:.2f}  "
          f"DD: {float(s['Max. Drawdown [%]']):.1f}%  "
          f"Trades: {int(s['# Trades'])}  "
          f"WR: {float(s['Win Rate [%]']) if str(s['Win Rate [%]']) != 'nan' else 0:.1f}%")
