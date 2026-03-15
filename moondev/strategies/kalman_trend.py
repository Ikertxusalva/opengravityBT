"""
Estrategia: KalmanTrendFollower
Tipo: Trend Following / Adaptive Filter
Logica: Kalman filter (Q=0.01, R=0.1) en close.
  - LONG: precio Kalman cruza POR ENCIMA del precio raw (filtered > close prev, filtered_prev < close_prev)
  - SHORT: precio Kalman cruza POR DEBAJO del raw
  - ADX > 20 para confirmar tendencia
  - SL: 2x ATR(14), TP: 4x ATR(14)
Fuente: ideas.txt #14
"""
import pandas as pd
import numpy as np
import pandas_ta as ta
from backtesting import Strategy, Backtest


def kalman_filter(prices: np.ndarray, Q: float = 0.01, R: float = 0.1) -> np.ndarray:
    """Simple 1D Kalman filter on price series."""
    n = len(prices)
    x_est = np.zeros(n)       # state estimate
    p_est = np.zeros(n)       # error covariance
    x_est[0] = prices[0]
    p_est[0] = 1.0

    for i in range(1, n):
        # Predict
        x_pred = x_est[i - 1]
        p_pred = p_est[i - 1] + Q

        # Update
        k = p_pred / (p_pred + R)
        x_est[i] = x_pred + k * (prices[i] - x_pred)
        p_est[i] = (1 - k) * p_pred

    return x_est


class KalmanTrendFollower(Strategy):
    kalman_Q = 0.01
    kalman_R = 0.1
    atr_length = 14
    adx_length = 14
    adx_threshold = 20
    sl_atr_mult = 2.0
    tp_atr_mult = 4.0

    def init(self):
        close = pd.Series(self.data.Close, index=range(len(self.data.Close)))
        high = pd.Series(self.data.High, index=range(len(self.data.High)))
        low = pd.Series(self.data.Low, index=range(len(self.data.Low)))

        # Kalman filtered price
        kf_vals = kalman_filter(close.values, Q=self.kalman_Q, R=self.kalman_R)
        self.kf = self.I(lambda: kf_vals, name="Kalman")

        # ATR
        atr_vals = ta.atr(high, low, close, length=self.atr_length)
        self.atr = self.I(lambda: atr_vals.values, name="ATR")

        # ADX
        adx_df = ta.adx(high, low, close, length=self.adx_length)
        self.adx = self.I(lambda: adx_df.iloc[:, 0].values, name="ADX")

    def next(self):
        if len(self.data) < self.adx_length + 5:
            return

        kf_now = self.kf[-1]
        kf_prev = self.kf[-2]
        price = self.data.Close[-1]
        price_prev = self.data.Close[-2]
        atr = self.atr[-1]
        adx = self.adx[-1]

        if any(np.isnan(x) for x in [kf_now, kf_prev, atr, adx]):
            return
        if atr <= 0:
            return

        # Only trade when there's a trend
        if adx < self.adx_threshold:
            return

        if not self.position:
            sl = atr * self.sl_atr_mult
            tp = atr * self.tp_atr_mult

            # Bullish cross: Kalman crosses above raw price
            if kf_prev < price_prev and kf_now > price:
                self.buy(sl=price - sl, tp=price + tp)
            # Bearish cross: Kalman crosses below raw price
            elif kf_prev > price_prev and kf_now < price:
                self.sell(sl=price + sl, tp=price - tp)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf

    data = yf.download("BTC-USD", period="1y", interval="1h", auto_adjust=True, progress=False)
    data.columns = [c[0] if isinstance(c, tuple) else c for c in data.columns]
    data = data[["Open", "High", "Low", "Close", "Volume"]].dropna()

    cash = max(10_000, data["Close"].max() * 3)
    bt = Backtest(data, KalmanTrendFollower, cash=cash, commission=0.001,
                  exclusive_orders=True, finalize_trades=True)
    s = bt.run()
    print(f"Return: {float(s['Return [%]']):.1f}%  "
          f"Sharpe: {float(s['Sharpe Ratio']) if str(s['Sharpe Ratio']) != 'nan' else 0:.2f}  "
          f"DD: {float(s['Max. Drawdown [%]']):.1f}%  "
          f"Trades: {int(s['# Trades'])}  "
          f"WR: {float(s['Win Rate [%]']) if str(s['Win Rate [%]']) != 'nan' else 0:.1f}%")
